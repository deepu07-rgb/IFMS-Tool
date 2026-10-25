from typing import List, Dict, Any, Tuple
from ifms_engine.layout_detector import LayoutDetector

class EmployeeBlockDetector:
    @staticmethod
    def _is_sr_word(w: Dict[str, Any]) -> bool:
        t = (w.get('text') or '').strip()
        if not t.isdigit():
            return False
        n = int(t)
        return 1 <= n <= 9999 and LayoutDetector.is_in_zone(w.get('x0', 0), w.get('y0', 0), LayoutDetector.COL_SR_NO)

    @staticmethod
    def _page_footer_min_y(page_words: List[Dict[str, Any]]) -> float:
        footer_y = 750.0
        for w in page_words:
            y = w.get('y0', 0)
            t = (w.get('text') or '').strip()
            tl = t.lower()
            if y < 180:
                continue
            if (
                tl.startswith('note')
                or tl.startswith('disclaimer')
                or (tl == 'group')
                or (tl == 'gross')
                or (tl == 'amount')
                or (tl == 'print')
                or (tl == 'forward')
            ) and y > 520:
                footer_y = min(footer_y, y)
        return footer_y

    @staticmethod
    def detect_blocks(words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Groups words into employee blocks based on vertical spacing and Sr. No markers.
        """
        blocks = []

        by_page = {}
        for w in words:
            by_page.setdefault(w.get('page_no', 0), []).append(w)

        for page_no in sorted(by_page.keys()):
            pwords = by_page[page_no]
            sr_markers = sorted(
                [w for w in pwords if EmployeeBlockDetector._is_sr_word(w)],
                key=lambda w: w.get('y0', 0)
            )
            if not sr_markers:
                continue

            header_cut = max(0, min(w.get('y0', 0) for w in sr_markers) - 6)
            footer_cut = EmployeeBlockDetector._page_footer_min_y(pwords)
            data_words = [
                w for w in pwords
                if header_cut <= w.get('y0', 0) < footer_cut
            ]
            data_words.sort(key=lambda w: (w.get('y0', 0), w.get('x0', 0)))

            current_block = None
            for w in data_words:
                if EmployeeBlockDetector._is_sr_word(w):
                    if current_block:
                        blocks.append(current_block)
                    current_block = []
                if current_block is not None:
                    current_block.append(w)
            if current_block:
                blocks.append(current_block)

        return blocks
