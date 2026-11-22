"""Keep V8's pinned source identity while avoiding irrelevant recursive submodule fetches."""
import json
import os
from pathlib import Path
import subprocess

setup = Path(__file__).resolve().parent
source = Path(os.environ.get('CODEX_IMAGE_BUILD_SOURCE', setup / '.build/codex-image-preview-src'))
revision = '90a65f887a0c0f048f3784afbcb320b373c8a2e0'
cached = list((setup / '.build/cargo/git/checkouts').glob('rusty_v8-*/*/Cargo.toml'))
v8 = next((p.parent for p in cached if subprocess.check_output(
    ['git', '-C', str(p.parent), 'rev-parse', 'HEAD'], text=True).strip() == revision), None)
if v8 is None:
    v8 = setup / '.build/codex-image-v8-metadata'
    if not (v8 / '.git').exists():
        subprocess.run(['git', 'clone', '--no-checkout', '--filter=blob:none',
                        'https://github.com/openai-oss-forks/rusty_v8.git', str(v8)], check=True)
    subprocess.run(['git', '-C', str(v8), '-c', 'submodule.recurse=false', 'checkout', revision], check=True)
manifest = source / 'codex-rs/Cargo.toml'
text = manifest.read_text()
original = 'v8 = { git = "https://github.com/openai-oss-forks/rusty_v8.git", rev = "' + revision + '" }'
replacement = 'v8 = { path = ' + json.dumps(str(v8.resolve())) + ' }'
if original in text:
    manifest.write_text(text.replace(original, replacement))
elif replacement not in text:
    raise SystemExit('Unexpected V8 patch; manifest unchanged')
print('V8 metadata source verified:', revision)
