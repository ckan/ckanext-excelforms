
class ExcelFormsException(Exception):
    pass

class BadExcelData(ExcelFormsException):
    def __init__(self, message):
        self.message = message
