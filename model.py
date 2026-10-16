from abc import ABC, abstractmethod
class Model(ABC):

    @abstractmethod
    def getTheChatModels(self):
        pass
    @abstractmethod
    def getTheEmbeddingModels(self):
        pass