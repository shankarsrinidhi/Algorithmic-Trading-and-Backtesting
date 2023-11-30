from __future__ import print_function
import datetime
import pandas as pd
# from sklearn.qda import QDA
from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis as QDA
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis as LDA
from sklearn.linear_model import LogisticRegression
import numpy as np
import yfinance as yf
from sklearn.svm import SVC

from strategy import Strategy
from event import SignalEvent
from backtest import Backtest
from data import HistoricCSVDataHandler
from execution import SimulatedExecutionHandler
from portfolio import Portfolio
from forecast import create_lagged_series
from sklearn.tree import DecisionTreeClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
# snp_forecast.py

from sklearn.ensemble import BaggingClassifier
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis



class SPYDailyForecastStrategy(Strategy):
    """
    S&P500 forecast strategy. It uses a Quadratic Discriminant Analyser to predict
    the returns for a subsequent time period and then generated long/exit signals based on the prediction.
    """

    def __init__(self, bars, events, model_name):
        self.bars = bars

        self.symbol_list = self.bars.symbol_list
        self.events = events
        self.datetime_now = datetime.datetime.utcnow()
        self.model_start_date = datetime.datetime(2001, 1, 10)
        self.model_end_date = datetime.datetime(2005, 12, 31)
        self.model_start_test_date = datetime.datetime(2005, 1, 1)
        self.long_market = False
        self.short_market = False
        self.bar_index = 0
        self.model_name = model_name
        self.model = self.create_symbol_forecast_model()

    def create_symbol_forecast_model(self):

        # initial data before transforming it to a lagged series
        time_series = yf.download(
        self.symbol_list[0],(self.model_start_date - datetime.timedelta(days=365)).strftime('%Y-%m-%d'),
        self.model_end_date.strftime('%Y-%m-%d'))
        
        # split into testing and training
        start_test = self.model_start_test_date
        
        train_ts = time_series[time_series.index < start_test]
        test_ts = time_series[time_series.index >= start_test]

        
        x_train_ts = train_ts[['Open','High','Low','Volume']]
        y_train_ts = train_ts['Close']

        x_test_ts = test_ts[['Open','High','Low','Volume']]
        y_test_ts = test_ts['Close']


        # Create a lagged series of the S&P500 US stock market index
        snpret = create_lagged_series(
        self.symbol_list[0], self.model_start_date, self.model_end_date, lags = 5
        )
        # Use the prior two days of returns as predictor # values, with direction as the response
        # X = snpret[["Lag1", "Lag2"]]
        X = snpret[["Lag1", "Lag2", "Lag3", "Lag4", "Lag5"]]
        # X = snpret[["Lag1", "Lag2"]]

        y = snpret["Direction"]
        # Create training and test sets
        #start_test = self.model_start_test_date (declared a few lines above)
        X_train = X[X.index < start_test]
        X_train = np.flip(X_train.to_numpy(),axis= 1)
        X_test = X[X.index >= start_test]
        X_test=  np.flip(X_test.to_numpy(), axis = 1)
        y_train = y[y.index < start_test]
        y_train = y_train.to_numpy()
        y_test = y[y.index >= start_test]
        y_test = y_test.to_numpy()

        if self.model_name == "QDA":
            model = QDA()
        elif self.model_name == "LDA":
            model = LDA()
        elif self.model_name == "LDA_BAGG":
            lda = LDA()
            model = BaggingClassifier(base_estimator=lda, n_estimators=10, random_state=0)
        elif self.model_name == "HYBRID":
            from statsmodels.tsa.arima.model import ARIMA

            # creating a range of values for the autoregressive (p), integrated (d), and moving average(q) components
            # represents the relationship between current and past observations; p indicates number of past observations in the model
            p_list = range(0,3)
            # represents differencing od time series data to make it stationary (removing trends or seasonality); d indicates number of times the series needs to be differenced
            d_list = range(0,2)
            # represents the relationship between the current observation and residual error; q indicates number of past residual errors in the model
            q_list = range(0,3)

            best_aic = float("inf")
            best_values = None

            # loops through the p d q possible values to find the ones that create the best fit for the ARIMA model
            for p in p_list:
                for d in d_list:
                    for q in q_list:
                        values = (p,d,q)
                        arima_model = ARIMA(y_train_ts, order = values)
                        try:
                            results = arima_model.fit()
                            aic = results.aic
                            if aic < best_aic:
                                best_values = values
                                best_aic = aic
                        except Exception as e:
                            print(f"An error occurred: {e}")

            #train ARIMA model with best p, d, q values
            arima_model = ARIMA(y_train_ts,order=best_values)
            arima_fit = arima_model.fit()

            arima_pred = arima_fit.predict(start=len(y_train_ts), end=len(y_train_ts) + len(y_test_ts) -1, typ='levels')

            # evaluate arima model
            arima_mse = np.sqrt(mean_squared_error(y_test_ts, arima_pred))
            print("ARIMA MSE:", arima_mse)

            # train random forest model
            model = RandomForestRegressor(n_estimators=100, random_state=29)
            model.fit(X_train,y_train)


        # model = SVC()
        # model = LogisticRegression()
        model.fit(X_train, y_train)
        return model


    def calculate_signals(self, event):
        """
            Calculate the SignalEvents based on market data.
        """

        sym = self.symbol_list[0]
        dt = self.datetime_now
        if event.type == 'MARKET':
            self.bar_index += 1
            if self.bar_index > 5:
                lags = self.bars.get_latest_bars_values(
                    self.symbol_list[0], "adj_close", N=6
                )
                # lags_norm = pd.DataFrame({'Lag1': [lags[1]],
                #                           'Lag2':[lags[2]] ,'Lag3':[lags[3]] ,'Lag4': [lags[4]],'Lag5': [lags[5]]})
                lags_norm = pd.DataFrame({'Lags': [lags[0], lags[1], lags[2], lags[3],
                                                   lags[4], lags[5]]}).pct_change() * 100
                # lags_norm.loc[0, 'Lags'] = 0.01

                # pred_series = pd.Series(
                # {
                # 'Lag1': lags[1] * 100.0,
                # 'Lag2': lags[2] * 100.0
                # }
                #     )

                pred_series = pd.Series(
                {
                'Lag1': lags_norm.loc[1, 'Lags'] ,
                'Lag2': lags_norm.loc[2, 'Lags'] ,
                'Lag3': lags_norm.loc[3, 'Lags'] ,
                    'Lag4': lags_norm.loc[4, 'Lags'] ,
                    'Lag5': lags_norm.loc[5, 'Lags'] ,

                }
                    )

                # pred = self.model.predict(pred_series)
                pred = self.model.predict(pred_series.values.reshape(1,-1))
                # pred = self.model.predict(pd.DataFrame({'Lag1':[pred_series.values[0]], 'Lag2':[pred_series.values[1]]}))
                if pred > 0 and not self.long_market:
                    self.long_market = True
                    signal = SignalEvent(1, sym, dt, 'LONG', 1.0)
                    self.events.put(signal)
                if pred < 0 and self.long_market:
                    self.long_market = False
                    signal = SignalEvent(1, sym, dt, 'EXIT', 1.0)
                    self.events.put(signal)


class DecisionStumpForecastStrategy(Strategy):
    """
    S&P500 forecast strategy. It uses a Quadratic Discriminant Analyser to predict
    the returns for a subsequent time period and then generated long/exit signals based on the prediction.
    """

    def __init__(self, bars, events):
        self.bars = bars

        self.symbol_list = self.bars.symbol_list
        self.events = events
        self.datetime_now = datetime.datetime.utcnow()
        self.model_start_date = datetime.datetime(2001, 1, 10)
        self.model_end_date = datetime.datetime(2005, 12, 31)
        self.model_start_test_date = datetime.datetime(2005, 1, 1)
        self.long_market = False
        self.short_market = False
        self.bar_index = 0
        self.model = self.create_symbol_forecast_model()

    @staticmethod
    def adaboost_pred(N, hypotheses, hypothesis_weights, X):
        Y_pred = np.zeros(N)
        for i in range(N):
            x = X[i, :]
            for (h, alpha) in zip(hypotheses, hypothesis_weights):
                y_pred = y_pred + alpha * h.predict(x)
                y_pred = np.sign(y_pred)
            Y_pred[i] = y_pred
        return y_pred

    def create_symbol_forecast_model(self):

        # Create a lagged series of the S&P500 US stock market index
        snpret = create_lagged_series(
            self.symbol_list[0], self.model_start_date, self.model_end_date, lags=5
        )
        # Use the prior two days of returns as predictor # values, with direction as the response
        # X = snpret[["Lag1", "Lag2"]]
        X = snpret[["Lag1", "Lag2", "Lag3", "Lag4", "Lag5"]]
        # X = snpret[["Lag1", "Lag2"]]

        y = snpret["Direction"]
        # Create training and test sets
        start_test = self.model_start_test_date
        X_train = X[X.index < start_test]
        X_train = np.flip(X_train.to_numpy(), axis=1)
        X_test = X[X.index >= start_test]
        X_test = np.flip(X_test.to_numpy(), axis=1)
        y_train = y[y.index < start_test]
        y_train = y_train.to_numpy()

        y_test = y[y.index >= start_test]
        y_test = y_test.to_numpy()

        # # model = QDA()
        # model = LDA()
        # # model = SVC()
        # # model = LogisticRegression()
        # model.fit(X_train, y_train)

        hypotheses = []
        hypothesis_weights = []

        N, _ = X_train.shape
        d = np.ones(N) / N


        num_iterations = 25
        for t in range(num_iterations):
            h = DecisionTreeClassifier(max_depth=1)

            h.fit(X_train, y_train, sample_weight=d)
            pred = h.predict(X_train)

            eps = d.dot(pred != y_train)
            alpha = (np.log(1 - eps) - np.log(eps)) / 2

            d = d * np.exp(- alpha * y_train * pred)
            d = d / d.sum()

            hypotheses.append(h)
            hypothesis_weights.append(alpha)

        y_pred = self.adaboost_pred(N, hypotheses, hypothesis_weights, X_train)
        train_acc =accuracy_score(y_train, y_pred)
        print("train accuracy: ", train_acc)

        model = (hypotheses, hypothesis_weights)
        return model

    def calculate_signals(self, event):
        """
            Calculate the SignalEvents based on market data.
        """

        sym = self.symbol_list[0]
        dt = self.datetime_now
        if event.type == 'MARKET':
            self.bar_index += 1
            if self.bar_index > 5:
                lags = self.bars.get_latest_bars_values(
                    self.symbol_list[0], "adj_close", N=6
                )
                # lags_norm = pd.DataFrame({'Lag1': [lags[1]],
                #                           'Lag2':[lags[2]] ,'Lag3':[lags[3]] ,'Lag4': [lags[4]],'Lag5': [lags[5]]})
                lags_norm = pd.DataFrame({'Lags': [lags[0], lags[1], lags[2], lags[3],
                                                   lags[4], lags[5]]}).pct_change() * 100
                # lags_norm.loc[0, 'Lags'] = 0.01

                # pred_series = pd.Series(
                # {
                # 'Lag1': lags[1] * 100.0,
                # 'Lag2': lags[2] * 100.0
                # }
                #     )

                pred_series = pd.Series(
                    {
                        'Lag1': lags_norm.loc[1, 'Lags'],
                        'Lag2': lags_norm.loc[2, 'Lags'],
                        'Lag3': lags_norm.loc[3, 'Lags'],
                        'Lag4': lags_norm.loc[4, 'Lags'],
                        'Lag5': lags_norm.loc[5, 'Lags'],

                    }
                )

                # pred = self.model.predict(pred_series)
                pred = self.model.predict(pred_series.values.reshape(1, -1))
                # pred = self.model.predict(pd.DataFrame({'Lag1':[pred_series.values[0]], 'Lag2':[pred_series.values[1]]}))
                if pred > 0 and not self.long_market:
                    self.long_market = True
                    signal = SignalEvent(1, sym, dt, 'LONG', 1.0)
                    self.events.put(signal)
                if pred < 0 and self.long_market:
                    self.long_market = False
                    signal = SignalEvent(1, sym, dt, 'EXIT', 1.0)
                    self.events.put(signal)





if __name__ == "__main__":
    csv_dir = 'data'  # CHANGE THIS!
    symbol_list = ['SPY']
    initial_capital = 100000.0
    heartbeat = 0.0
    start_date = datetime.datetime(2006, 1, 3)
    backtest = Backtest(
        csv_dir, symbol_list, initial_capital, heartbeat,
        start_date, HistoricCSVDataHandler, SimulatedExecutionHandler, Portfolio, SPYDailyForecastStrategy
    )
    backtest.simulate_trading()

def run_snp_forecast(symbol_list, initial_capital, trade_volume, model_name):
    csv_dir = 'data'  # CHANGE THIS!
    # symbol_list = ['SPY']
    # initial_capital = 100000.0

    heartbeat = 0.0
    start_year = 2006
    # start_year = 2015
    start_date = datetime.datetime(start_year, 1, 3)
    backtest = Backtest(
        csv_dir, symbol_list, initial_capital, heartbeat,
        start_date, HistoricCSVDataHandler, SimulatedExecutionHandler, Portfolio, SPYDailyForecastStrategy, model_name
    )
    total_gain , returns, equity_curve, drawdown = backtest.simulate_trading(trade_volume)

    return total_gain, returns, equity_curve, drawdown



def run_adaboost_decision_stumps_forecast(symbol_list, initial_capital, trade_volume):
    csv_dir = 'data'  # CHANGE THIS!
    # symbol_list = ['SPY']
    # initial_capital = 100000.0

    heartbeat = 0.0
    start_date = datetime.datetime(2006, 1, 3)
    backtest = Backtest(
        csv_dir, symbol_list, initial_capital, heartbeat,
        start_date, HistoricCSVDataHandler, SimulatedExecutionHandler, Portfolio, DecisionStumpForecastStrategy
    )
    total_gain , returns, equity_curve, drawdown = backtest.simulate_trading(trade_volume)

    return total_gain, returns, equity_curve, drawdown