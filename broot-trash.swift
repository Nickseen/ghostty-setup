import Foundation

guard CommandLine.arguments.count == 2 else { exit(2) }
do {
    var destination: NSURL?
    try FileManager.default.trashItem(
        at: URL(fileURLWithPath: CommandLine.arguments[1]),
        resultingItemURL: &destination
    )
    guard let path = destination?.path else { exit(1) }
    let result = try JSONSerialization.data(withJSONObject: ["path": path])
    FileHandle.standardOutput.write(result)
} catch {
    FileHandle.standardError.write(Data(error.localizedDescription.utf8))
    exit(1)
}
