// hamster-lm — thin CLI over Apple's on-device Foundation Models (macOS 26+).
//
//   hamster-lm [--instructions "<system text>"] [--max-tokens N] < prompt.txt
//   hamster-lm --check          exit 0 + "available" when the model can run, else exit 3 + reason
//
// Reads the prompt from stdin, prints the reply to stdout. Exit codes: 0 ok,
// 2 usage, 3 model unavailable, 4 generation failed. Stdlib + FoundationModels only.
import Foundation
import FoundationModels

func die(_ code: Int32, _ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(code)
}

var instructions = "You are a terse assistant. Answer with only what was asked, no preamble."
var maxTokens = 800
var check = false
var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    switch a {
    case "--instructions": guard !args.isEmpty else { die(2, "--instructions needs a value") }; instructions = args.removeFirst()
    case "--max-tokens": guard let n = Int(args.isEmpty ? "" : args.removeFirst()) else { die(2, "--max-tokens needs an int") }; maxTokens = n
    case "--check": check = true
    case "-h", "--help": print("usage: hamster-lm [--instructions S] [--max-tokens N] < prompt | --check"); exit(0)
    default: die(2, "unknown argument \(a)")
    }
}

let model = SystemLanguageModel.default
switch model.availability {
case .available: break
case .unavailable(let reason): die(3, "unavailable: \(reason)")
}
if check { print("available"); exit(0) }

let data = FileHandle.standardInput.readDataToEndOfFile()
guard let prompt = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines), !prompt.isEmpty else {
    die(2, "empty prompt on stdin")
}

let semaphore = DispatchSemaphore(value: 0)
var exitCode: Int32 = 0
Task {
    do {
        let session = LanguageModelSession(instructions: instructions)
        let options = GenerationOptions(maximumResponseTokens: maxTokens)
        let response = try await session.respond(to: prompt, options: options)
        print(response.content)
    } catch {
        FileHandle.standardError.write("generation failed: \(error)\n".data(using: .utf8)!)
        exitCode = 4
    }
    semaphore.signal()
}
semaphore.wait()
exit(exitCode)
