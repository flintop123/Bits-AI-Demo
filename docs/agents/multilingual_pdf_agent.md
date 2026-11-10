# Multilingual PDF Agent

## Responsibility

The agent extracts page-aware evidence from English, Hindi and mixed-language agriculture PDFs. It uses the embedded text layer when usable and invokes Hindi/English OCR only when the page requires it.

## Inputs and outputs

| Item | Contract |
|---|---|
| Input | A local PDF or an enabled entry in `sources/agriculture_sources.yaml` |
| Decision | Direct extraction or OCR fallback for each page |
| Tools | pypdf, PyMuPDF, Tesseract, Pillow |
| Output | Bounded text chunks with page and extraction metadata |
| Storage | `bihar_agriculture.agriculture_documents` |

Each chunk contains the document title, page number, chunk index, normalized text, detected language, extraction method, content hash, source file and source URL.

## Model and fixed-code boundary

No generative model chooses or rewrites extracted evidence. OCR selection, language detection, Unicode normalization and chunking are deterministic. Tesseract performs OCR but does not generate an answer.

## Error case

When OCR is explicitly required and Tesseract or the requested language data is unavailable, the agent raises `OCRUnavailableError`. A page with neither usable direct text nor usable OCR is counted as skipped.

## Limitations

- OCR quality depends on scan resolution, layout and font quality.
- Tables are preserved as OCR text rather than reconstructed as perfect cell geometry.
- Page numbers identify the PDF page processed; printed page labels inside a document may differ.
