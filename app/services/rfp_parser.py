"""
RFP Parser — extracts clean text from PDF, DOCX, and plain-text documents
"""
import logging
from app.utils.text_cleaner import clean_html_text

logger = logging.getLogger(__name__)


class RFPParser:
    """Parses uploaded RFP documents into clean text."""

    def parse(self, file_bytes: bytes, filename: str) -> str:
        """
        Parse an uploaded file into clean text.

        Args:
            file_bytes: Raw file bytes
            filename:   Original filename (used to detect format)

        Returns:
            Cleaned text string
        """
        name_lower = filename.lower()

        if name_lower.endswith(".pdf"):
            return self._parse_pdf(file_bytes)
        elif name_lower.endswith(".docx"):
            return self._parse_docx(file_bytes)
        elif name_lower.endswith((".txt", ".eml", ".md")):
            return self._parse_text(file_bytes)
        else:
            logger.warning(f"Unsupported file type: {filename}. Attempting plain-text decode.")
            return self._parse_text(file_bytes)

    def _parse_pdf(self, file_bytes: bytes) -> str:
        try:
            import pdfplumber
            import io
            text_parts = []
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            raw = "\n".join(text_parts)
            return clean_html_text(raw)
        except ImportError:
            raise RuntimeError(
                "pdfplumber is required for PDF parsing. "
                "Install it with: pip install pdfplumber"
            )
        except Exception as e:
            logger.error(f"PDF parsing failed: {e}")
            raise

    def _parse_docx(self, file_bytes: bytes) -> str:
        try:
            import docx
            import io
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            raw = "\n".join(paragraphs)
            return clean_html_text(raw)
        except ImportError:
            raise RuntimeError(
                "python-docx is required for DOCX parsing. "
                "Install it with: pip install python-docx"
            )
        except Exception as e:
            logger.error(f"DOCX parsing failed: {e}")
            raise

    def _parse_text(self, file_bytes: bytes) -> str:
        try:
            raw = file_bytes.decode("utf-8", errors="replace")
            return clean_html_text(raw)
        except Exception as e:
            logger.error(f"Text parsing failed: {e}")
            raise


# Singleton
_rfp_parser = None


def get_rfp_parser() -> RFPParser:
    global _rfp_parser
    if _rfp_parser is None:
        _rfp_parser = RFPParser()
    return _rfp_parser
