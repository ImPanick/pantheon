# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one refusal Apollo's rules raise: a sentence a person can read."""


class ApolloRefused(Exception):
    """Something Apollo will not do, and why, in a sentence that ends in a full stop."""

    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status

    def body(self) -> dict:
        return {"detail": self.sentence}
