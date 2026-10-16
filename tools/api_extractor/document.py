class Documents:
    def __init__(self, page_content, metadata, source):
        self._page_content = page_content
        self._metadata = metadata
        self._source = source

    @property
    def page_content(self):
        return self._page_content
    
    @page_content.setter
    def page_content(self, value):
        if not isinstance(value, str):
            raise ValueError("page_content must be a string")
        self._page_content = value

    @property
    def metadata(self):
        return self._metadata
    
    @metadata.setter
    def metadata(self, value):
        if not isinstance(value, dict):
            raise ValueError("metadata must be a dictionary")
        self._metadata = value


    @property
    def source(self):
        return self._source
    
    @source.setter
    def source(self, value):
        if not isinstance(value, str):
            raise ValueError("source must be a string")
        self._source = value            