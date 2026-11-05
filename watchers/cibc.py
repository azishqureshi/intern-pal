"""CIBC campus board, verified using full posting details."""
from watchers.workday import Board, fetch_board

BOARD = Board("cibc", "CIBC", "cibc", "campus", facets={
    "Country": ["a30a87ed25634629aa6c3958aa2b91ea"],
})


def fetch_postings():
    return fetch_board(BOARD)
