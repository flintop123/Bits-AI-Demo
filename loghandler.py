import logging

def getLogger():
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')


        # Add formatter to handlers
        console_handler.setFormatter(formatter)

        # Add handlers to the logger
        logger.addHandler(console_handler)
    return logger