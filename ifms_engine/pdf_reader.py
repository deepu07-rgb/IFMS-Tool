import fitz
from typing import List, Dict, Any

class PDFReader:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.doc = fitz.open(filepath)
    
    def extract_words(self) -> List[Dict[str, Any]]:
        """
        Extract words from all pages with coordinates and metadata.
        """
        all_words = []
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            # fitz get_text("words") returns list of tuples: (x0, y0, x1, y1, "word", block_no, line_no, word_no)
            words = page.get_text("words")
            for w in words:
                all_words.append({
                    'page_no': page_num + 1,
                    'x0': w[0],
                    'y0': w[1],
                    'x1': w[2],
                    'y1': w[3],
                    'text': w[4],
                    'block_no': w[5],
                    'line_no': w[6]
                })
        return all_words

    def get_page_count(self):
        return len(self.doc)

    def close(self):
        self.doc.close()
