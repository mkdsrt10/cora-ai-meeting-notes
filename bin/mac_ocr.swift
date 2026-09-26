import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    fputs("Usage: mac-ocr <image_path>\n", stderr)
    exit(1)
}

let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)

guard let image = NSImage(contentsOf: url),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("Error: Could not load image at \(path)\n", stderr)
    exit(1)
}

let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        fputs("Vision OCR Error: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
    guard let observations = request.results as? [VNRecognizedTextObservation] else { return }
    let lines = observations.compactMap { $0.topCandidates(1).first?.string }
    print(lines.joined(separator: "\n"))
}

request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("Handler error: \(error.localizedDescription)\n", stderr)
    exit(1)
}
