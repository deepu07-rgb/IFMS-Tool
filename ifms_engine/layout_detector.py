class LayoutDetector:
    # Column X boundaries based on IFMS Inner Sheet pattern
    COL_SR_NO = (0, 40)
    COL_IDENTITY = (40, 110)
    COL_NAME_DESIG = (110, 240)
    COL_ALLOWANCE = (240, 420)
    COL_GROSS = (420, 468)
    COL_DEDUCTION = (468, 660)
    COL_SUM_DEDUCTION = (660, 715)
    COL_NET = (715, 900)

    # Zone Y boundaries
    HEADER_MAX_Y = 200
    FOOTER_MIN_Y = 530

    @staticmethod
    def is_in_zone(x, y, col_range):
        return col_range[0] <= x < col_range[1]
