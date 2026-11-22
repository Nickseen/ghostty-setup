on run argv
    set previewPid to (item 1 of argv) as integer
    tell application "System Events"
        repeat 25 times
            if exists (first application process whose unix id is previewPid) then
                set previewProcess to first application process whose unix id is previewPid
                set frontmost of previewProcess to true
                if (count of windows of previewProcess) > 0 then return
            end if
            delay 0.1
        end repeat
    end tell
end run
