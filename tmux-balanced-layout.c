/* Private tmux 3.8 extension. Included at the end of layout.c. */
struct balanced_cell {
	struct layout_cell *cell;
	struct layout_geometry original, expected;
	enum layout_type type;
	u_int pane, flags;
};

struct balanced_drag {
	int active;
	u_int window, width, height, count, border, ncells;
	int origin;
	enum layout_type type;
	struct balanced_cell *cells;
	struct layout_cell **siblings;
	int *sizes, *capacity, *losses, *desired;
};

void
layout_resize_balanced_reset(struct client *c)
{
	struct balanced_drag *drag = c->tty.mouse_resize_state;

	if (drag == NULL)
		return;
	free(drag->cells);
	free(drag->siblings);
	free(drag->sizes);
	free(drag->capacity);
	free(drag->losses);
	free(drag->desired);
	free(drag);
	c->tty.mouse_resize_state = NULL;
}

static void
balanced_snapshot(struct balanced_drag *drag, struct layout_cell *cell)
{
	struct balanced_cell *saved;
	struct layout_cell *child;

	drag->cells = xreallocarray(drag->cells, drag->ncells + 1,
	    sizeof *drag->cells);
	saved = &drag->cells[drag->ncells++];
	saved->cell = cell;
	saved->original = saved->expected = cell->g;
	saved->type = cell->type;
	saved->flags = cell->flags;
	saved->pane = cell->wp != NULL ? cell->wp->id : UINT_MAX;
	TAILQ_FOREACH(child, &cell->cells, entry)
		balanced_snapshot(drag, child);
}

/* Check live pointers before dereferencing any saved cell after a split/close. */
static int
balanced_valid(struct balanced_drag *drag, struct layout_cell *cell, u_int *index)
{
	struct balanced_cell *saved;
	struct layout_cell *child;

	if (*index >= drag->ncells)
		return (0);
	saved = &drag->cells[(*index)++];
	if (saved->cell != cell || saved->type != cell->type ||
	    saved->flags != cell->flags ||
	    saved->pane != (cell->wp != NULL ? cell->wp->id : UINT_MAX) ||
	    memcmp(&saved->expected, &cell->g, sizeof cell->g) != 0)
		return (0);
	TAILQ_FOREACH(child, &cell->cells, entry) {
		if (!balanced_valid(drag, child, index))
			return (0);
	}
	return (1);
}

static int
balanced_position(struct mouse_event *m, int previous, int horizontal)
{
	int x = (previous ? m->lx : m->x) + m->ox;
	int y = (previous ? m->ly : m->y) + m->oy;

	if (m->statusat == 0 && y >= (int)m->statuslines)
		y -= m->statuslines;
	else if (m->statusat > 0 && y >= m->statusat)
		y = m->statusat - 1;
	return (horizontal ? x : y);
}

static void
balanced_start(struct balanced_drag *drag, struct window *w,
    struct mouse_event *m)
{
	struct layout_cell *border, *child, *nearby;
	static const int offsets[][2] = {{0, 1}, {1, 0}, {0, -1}, {-1, 0}};
	u_int index;
	int x, y;

	if (m->b & MOUSE_MASK_META)
		return;
	x = balanced_position(m, 1, 1);
	y = balanced_position(m, 1, 0);
	border = layout_search_by_border(w->layout_root, x, y);
	if (border == NULL || border->parent == NULL)
		return;
	/* An intersection may resize two axes; retain tmux's native corner drag. */
	for (index = 0; index < nitems(offsets); index++) {
		nearby = layout_search_by_border(w->layout_root,
		    x + offsets[index][0], y + offsets[index][1]);
		if (nearby != NULL && nearby->parent != border->parent)
			return;
	}
	drag->type = border->parent->type;
	TAILQ_FOREACH(child, &border->parent->cells, entry) {
		if (layout_cell_is_tiled(child) || layout_cell_has_tiled_child(child))
			drag->count++;
	}
	if (drag->count < 3)
		return; /* Two siblings already behave exactly like native resizing. */
	drag->siblings = xcalloc(drag->count, sizeof *drag->siblings);
	drag->sizes = xcalloc(drag->count, sizeof *drag->sizes);
	drag->capacity = xcalloc(drag->count, sizeof *drag->capacity);
	drag->losses = xcalloc(drag->count, sizeof *drag->losses);
	drag->desired = xcalloc(drag->count, sizeof *drag->desired);
	index = 0;
	TAILQ_FOREACH(child, &border->parent->cells, entry) {
		if (!layout_cell_is_tiled(child) && !layout_cell_has_tiled_child(child))
			continue;
		if (child == border)
			drag->border = index;
		drag->siblings[index] = child;
		drag->sizes[index] = drag->type == LAYOUT_LEFTRIGHT ?
		    child->g.sx : child->g.sy;
		drag->capacity[index] = layout_resize_check(w, child, drag->type);
		index++;
	}
	if (drag->border + 1 >= drag->count)
		return;
	drag->origin = drag->type == LAYOUT_LEFTRIGHT ? x : y;
	drag->window = w->id;
	drag->width = w->sx;
	drag->height = w->sy;
	balanced_snapshot(drag, w->layout_root);
	drag->active = 1;
}

/* Equal absolute losses; only saturated donors stop participating. */
static int
balanced_displacement(struct balanced_drag *drag, u_int grow, int amount,
    int positive)
{
	u_int i, j, index, available, rank;
	int remaining = amount, quotient, extra, wanted, loss, displacement = 0;

	memset(drag->losses, 0, drag->count * sizeof *drag->losses);
	while (remaining > 0) {
		available = 0;
		for (i = 0; i < drag->count; i++) {
			if (i != grow && drag->losses[i] < drag->capacity[i])
				available++;
		}
		if (available == 0)
			break;
		quotient = remaining / available;
		extra = remaining % available;
		rank = 0;
		for (j = 0; j < drag->count; j++) {
			index = positive ? (grow + 1 + j) % drag->count : j;
			if (index == grow || drag->losses[index] == drag->capacity[index])
				continue;
			wanted = quotient + (rank++ < (u_int)extra);
			loss = drag->capacity[index] - drag->losses[index];
			if (loss > wanted)
				loss = wanted;
			drag->losses[index] += loss;
			remaining -= loss;
		}
	}
	for (i = 0; i < drag->count; i++) {
		drag->desired[i] = drag->sizes[i] - drag->losses[i];
		if (i == grow)
			drag->desired[i] += amount;
		if (i <= drag->border)
			displacement += drag->desired[i] - drag->sizes[i];
	}
	return (positive ? displacement : -displacement);
}

/* A complete mouse frame is computed and applied in the server event loop. */
int
layout_resize_balanced(struct client *c, struct window *w, struct mouse_event *m)
{
	struct balanced_drag *drag = c->tty.mouse_resize_state;
	u_int i, index = 0, grow;
	int delta, requested, positive, low, high, middle, displacement, maximum;
	int changed = 0;

	if (drag == NULL) {
		drag = xcalloc(1, sizeof *drag);
		c->tty.mouse_resize_state = drag;
		balanced_start(drag, w, m);
	}
	if (drag->active == 0)
		return (0);
	if (drag->active == -1)
		return (1);
	if (w->id != drag->window || w->sx != drag->width ||
	    w->sy != drag->height || (w->flags & WINDOW_ZOOMED) ||
	    !balanced_valid(drag, w->layout_root, &index) || index != drag->ncells) {
		drag->active = -1;
		return (1);
	}
	delta = balanced_position(m, 0, drag->type == LAYOUT_LEFTRIGHT) - drag->origin;
	positive = delta >= 0;
	requested = positive ? delta : -delta;
	grow = positive ? drag->border : drag->border + 1;
	low = high = 0;
	for (i = 0; i < drag->count; i++) {
		if (i != grow)
			high += drag->capacity[i];
	}
	maximum = balanced_displacement(drag, grow, high, positive);
	if (requested > maximum)
		requested = maximum;
	/* Complete each equal-share round; at a hard stop avoid needless growth. */
	if (requested == 0)
		high = 0;
	while (low < high) {
		if (requested < maximum) {
			middle = low + (high - low + 1) / 2;
			displacement = balanced_displacement(drag, grow, middle, positive);
			if (displacement <= requested)
				low = middle;
			else
				high = middle - 1;
		} else {
			middle = low + (high - low) / 2;
			if (balanced_displacement(drag, grow, middle, positive) < requested)
				low = middle + 1;
			else
				high = middle;
		}
	}
	balanced_displacement(drag, grow, low, positive);
	for (i = 0; i < drag->count; i++) {
		int size = drag->type == LAYOUT_LEFTRIGHT ?
		    drag->siblings[i]->g.sx : drag->siblings[i]->g.sy;
		if (size != drag->desired[i])
			changed = 1;
	}
	if (!changed)
		return (1);
	/* Work from the initial geometry so rounding and reversals never drift. */
	for (i = 0; i < drag->ncells; i++)
		drag->cells[i].cell->g = drag->cells[i].original;
	for (i = 0; i < drag->count; i++)
		layout_resize_adjust(w, drag->siblings[i], drag->type,
		    drag->desired[i] - drag->sizes[i]);
	layout_fix_offsets(w);
	layout_fix_panes(w, NULL);
	for (i = 0; i < drag->ncells; i++)
		drag->cells[i].expected = drag->cells[i].cell->g;
	events_fire_window("window-layout-changed", w);
	server_redraw_window(w);
	return (1);
}
