import Foundation
import CoreText

guard CommandLine.arguments.count == 2 else { exit(2) }
var error: Unmanaged<CFError>?
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let registered = CTFontManagerRegisterFontsForURL(url as CFURL, .persistent, &error)
if !registered, let error = error?.takeRetainedValue(), CFErrorGetCode(error) != 105 {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
let font = CTFontCreateWithName("Broot Icons Visual Studio Code" as CFString, 14, nil)
print(CTFontCopyFamilyName(font))
let sample = "\u{1002D2}" // the Rust file icon in Broot's VS Code icon theme
let base = CTFontCreateWithName("Menlo" as CFString, 14, nil)
let fallback = CTFontCreateForString(base, sample as CFString,
    CFRange(location: 0, length: (sample as NSString).length))
print("Icon fallback: \(CTFontCopyFamilyName(fallback))")
