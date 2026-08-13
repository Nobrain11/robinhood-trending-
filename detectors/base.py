from abc import ABC, abstractmethod

from app.models import Launch


class Detector(ABC):

    name: str

    address: str

    topic0: str

    start_block: int


    @abstractmethod
    def decode_launch(
        self,
        w3,
        log,
    ) -> Launch:

        raise NotImplementedError
