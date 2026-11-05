"""Verified public Workday boards; all use the same detail filter."""
from watchers.workday import Board, fetch_board

RBC = Board('rbc', 'RBC', 'rbc', 'RBCEARLYTALENT1')
BMO = Board('bmo', 'BMO', 'bmo', 'Campus', facets={
    'Country': ['a30a87ed25634629aa6c3958aa2b91ea'],
})
TD = Board('td', 'TD', 'td', 'TD_Bank_Careers', facets={
    'locationCountry': ['a30a87ed25634629aa6c3958aa2b91ea'],
    'jobFamily': ['de769652963501ab29a8b80c0704c3aa'],  # Official Campus category
})


def fetch_rbc():
    return fetch_board(RBC)


def fetch_bmo():
    return fetch_board(BMO)


def fetch_td():
    return fetch_board(TD)
