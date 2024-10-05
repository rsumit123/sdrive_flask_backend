import logging
import datetime

class MongoDBHandler(logging.Handler):
    def __init__(self, db_collection):
        super().__init__()
        self.collection = db_collection

    def emit(self, record):
        try:
            log_entry = {
                "timestamp": datetime.datetime.utcnow(),
                "level": record.levelname,
                "message": self.format(record),
                "module": record.module,
                "funcName": record.funcName,
                "lineno": record.lineno
            }
            self.collection.insert_one(log_entry)
        except Exception:
            self.handleError(record)
