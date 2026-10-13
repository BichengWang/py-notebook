import os

import robin_stocks as rs
rs.login(
    username=os.environ['ROBINHOOD_USERNAME'],
    password=pw, 
    expiresIn=86400, 
    by_sms=True)
