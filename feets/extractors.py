#!/usr/bin/env python
# -*- coding: utf-8 -*-

# The MIT License (MIT)

# Copyright (c) 2017 Juan Cabral

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# =============================================================================
# FUTURE
# =============================================================================

from __future__ import unicode_literals, print_function


# =============================================================================
# DOCS
# =============================================================================

__doc__ = """Features extractors classes and register utilities"""


# =============================================================================
# IMPORTS
# =============================================================================

import math
import inspect
from collections import namedtuple

import six

import numpy as np

from scipy import stats
from scipy.optimize import minimize
from scipy.optimize import curve_fit
from statsmodels.tsa import stattools
from scipy.interpolate import interp1d

from . import err
from .libs import lomb


# =============================================================================
# CONSTANTS
# =============================================================================

DATA_MAGNITUDE = "magnitude"
DATA_TIME = "time"
DATA_ERROR = "error"
DATA_MAGNITUDE2 = "magnitude2"
DATA_ALIGNED_MAGNITUDE = "aligned_magnitude"
DATA_ALIGNED_MAGNITUDE2 = "aligned_magnitude2"
DATA_ALIGNED_TIME = "aligned_time"
DATA_ALIGNED_ERROR = "aligned_error"
DATA_ALIGNED_ERROR2 = "aligned_error2"


DATA_IDXS = {
    DATA_MAGNITUDE: 0,
    DATA_TIME: 1,
    DATA_ERROR: 2,
    DATA_MAGNITUDE2: 3,
    DATA_ALIGNED_MAGNITUDE: 4,
    DATA_ALIGNED_MAGNITUDE2: 5,
    DATA_ALIGNED_TIME: 6,
    DATA_ALIGNED_ERROR: 7,
    DATA_ALIGNED_ERROR2: 8
}

DATAS = tuple([d[0] for d in sorted(DATA_IDXS.items(), key=lambda di: di[1])])


# =============================================================================
# REGISTER UTILITY
# =============================================================================

_extractors = {}


def register_extractor(cls):
    if not inspect.isclass(cls) or not issubclass(cls, Extractor):
        msg = "'cls' must be a subclass of Extractor. Found: {}"
        raise TypeError(msg.format(cls))
    for d in cls._conf.dependencies:
        if d not in _extractors.keys():
            msg = "Dependency '{}' from extractor {}".format(d, cls)
            raise err.FeatureNotFound(msg)

    _extractors.update((f, cls) for f in cls._conf.features)
    return cls


def registered_extractors():
    return dict(_extractors)


def is_registered(obj):
    if isinstance(obj, six.string_types):
        features = [obj]
    elif not inspect.isclass(obj) or not issubclass(obj, Extractor):
        msg = "'cls' must be a subclass of Extractor. Found: {}"
        raise TypeError(msg.format(obj))
    else:
        features = obj._conf.features
    return {f: (f in _extractors) for f in features}


def available_features():
    return _extractors.keys()


def extractor_of(feature):
    return _extractors[feature]



# =============================================================================
# BASE CLASS
# =============================================================================

ExtractorConf = namedtuple(
    "ExtractorConf", ["data", "dependencies", "params", "features"])


class ExtractorMeta(type):

    def __new__(mcls, name, bases, namespace):
        cls = super(ExtractorMeta, mcls).__new__(mcls, name, bases, namespace)

        try:
            cls != Extractor
        except NameError:
            return cls

        if not hasattr(cls, "data"):
            msg = "'{}' must redefine {}"
            raise ExtractorError(msg.format(cls, "data attribute"))
        if not cls.data:
            msg = "'data' can't be empty"
            raise ExtractorError(msg)
        for d in cls.data:
            if d not in DATAS:
                msg = "'data' must be a iterable with values in {}. Found '{}'"
                raise ExtractorError(msg.format(DATAS, d))
        if len(set(cls.data)) != len(cls.data):
            msg = "'data' has duplicated values: {}"
            raise ExtractorError(msg.format(cls.data))

        if not hasattr(cls, "features"):
            msg = "'{}' must redefine {}"
            raise ExtractorError(msg.format(cls, "features attribute"))
        if not cls.features:
            msg = "'features' can't be empty"
            raise ExtractorError(msg)
        for f in cls.features:
            if not isinstance(f, six.string_types):
                msg = "Feature name must be an instance of string. Found {}"
                raise TypeError(msg.format(type(f)))
            if f in DATAS:
                msg = "Params can't be in {}".format(DATAS)
                raise err.DataReservedNameError(msg)

        if len(set(cls.features)) != len(cls.features):
            msg = "'features' has duplicated values: {}"
            raise ExtractorError(msg.format(cls.features))

        if cls.fit == Extractor.fit:
            msg = "'{}' must redefine {}"
            raise ExtractorError(msg.format(cls, "fit method"))

        if not hasattr(cls, "dependencies"):
            cls.dependencies = ()
        for d in cls.dependencies:
            if not isinstance(d, six.string_types):
                msg = "Dependencies must be an instance of string. Found {}"
                raise TypeError(msg.format(type(d)))

        if not hasattr(cls, "params"):
            cls.params = {}
        for p, default in cls.params.items():
            if not isinstance(p, six.string_types):
                msg = "Params name must be an instance of string. Found {}"
                raise TypeError(msg.format(type(p)))
            if p in DATAS:
                msg = "Params can't be in {}".format(DATAS)
                raise err.DataReservedNameError(msg)

        cls._conf = ExtractorConf(
            data=frozenset(cls.data),
            dependencies=frozenset(cls.dependencies),
            params=tuple(cls.params.items()),
            features=frozenset(cls.features))

        del cls.data, cls.dependencies, cls.params, cls.features

        return cls


@six.add_metaclass(ExtractorMeta)
class Extractor(object):

    def __init__(self, space):
        self.space = space
        self.name = type(self).__name__
        self.params = {}
        ns = self.space.params_by_features(self._conf.features)
        for p, d in self._conf.params:
            self.params[p] = ns.get(p, d)

    def __repr__(self):
        return str(self)

    def __str__(self):
        if not hasattr(self, "__str"):
            params = dict(self._conf.params)
            params.update(self.params)
            if params:
                params = ", ".join([
                    "{}={}".format(k, v) for k, v in params.items()])
            else:
                params = ""
            self.__str = "{}({})".format(self.name, params)
        return self.__str

    def setup(self):
        pass

    def fit(self):
        raise NotImplementedError()

    def teardown(self):
        pass

    def extract(self, data, dependencies):
        kwargs = {k: dependencies[k] for k in self._conf.dependencies}
        for d in self._conf.data:
            idx = DATA_IDXS[d]
            kwargs[d] = data[idx]
        kwargs.update(self.params)
        try:
            self.setup()
            features = self.fit(**kwargs)
            if not hasattr(features, "__iter__"):
                features = (features,)
            return dict(zip(self._conf.features, features))
        finally:
            self.teardown()


# =============================================================================
# EXTRACTORS
# =============================================================================

class Amplitude(Extractor):
    """Half the difference between the maximum and the minimum magnitude"""

    data = ['magnitude']
    features = ['Amplitude']

    def fit(self, magnitude):
        N = len(magnitude)
        sorted_mag = np.sort(magnitude)

        return (np.median(sorted_mag[-math.ceil(0.05 * N):]) -
                np.median(sorted_mag[0:math.ceil(0.05 * N)])) / 2.0


class RCS(Extractor):
    """Range of cumulative sum"""

    data = ['magnitude']
    features = ['Rcs']

    def fit(self, magnitude):
        sigma = np.std(magnitude)
        N = len(magnitude)
        m = np.mean(magnitude)
        s = np.cumsum(magnitude - m) * 1.0 / (N * sigma)
        R = np.max(s) - np.min(s)
        return R


class StetsonK(Extractor):
    data = ['magnitude', 'error']
    features = ['StetsonK']

    def fit(self, magnitude, error):
        mean_mag = (np.sum(magnitude/(error*error)) /
                    np.sum(1.0 / (error * error)))

        N = len(magnitude)
        sigmap = (np.sqrt(N * 1.0 / (N - 1)) *
                  (magnitude - mean_mag) / error)

        K = (1 / np.sqrt(N * 1.0) *
             np.sum(np.abs(sigmap)) / np.sqrt(np.sum(sigmap ** 2)))

        return K


class MeanVariance(Extractor):
    """variability index"""

    data = ['magnitude']
    features = ['Meanvariance']

    def fit(self, magnitude):
        return np.std(magnitude) / np.mean(magnitude)


class AutocorLength(Extractor):
    data = ['magnitude']
    features = ['Autocor_length']
    params = {"nlags": 100}

    def fit(self, magnitude, nlags):

        AC = stattools.acf(magnitude, nlags=nlags)
        k = next((index for index, value in
                 enumerate(AC) if value < np.exp(-1)), None)

        while k is None:
            nlags = nlags + 100
            AC = stattools.acf(magnitude, nlags=nlags)
            k = next((index for index, value in
                      enumerate(AC) if value < np.exp(-1)), None)

        return k


class SlottedA_length(Extractor):
    """T: tau (slot size in days. default: 4)"""

    data = ["magnitude", "time"]
    features = ["SlottedA_length"]
    params = {"T": None}

    def slotted_autocorrelation(self, data, time, T, K,
                                second_round=False, K1=100):

        slots, i = np.zeros((K, 1)), 1

        # make time start from 0
        time = time - np.min(time)

        # subtract mean from mag values
        m = np.mean(data)
        data = data - m

        prod = np.zeros((K, 1))
        pairs = np.subtract.outer(time, time)
        pairs[np.tril_indices_from(pairs)] = 10000000

        ks = np.int64(np.floor(np.abs(pairs) / T + 0.5))

        # We calculate the slotted autocorrelation for k=0 separately
        idx = np.where(ks == 0)
        prod[0] = ((sum(data ** 2) + sum(data[idx[0]] *
                   data[idx[1]])) / (len(idx[0]) + len(data)))
        slots[0] = 0

        # We calculate it for the rest of the ks
        if second_round is False:
            for k in np.arange(1, K):
                idx = np.where(ks == k)
                if len(idx[0]) != 0:
                    prod[k] = sum(data[idx[0]] * data[idx[1]]) / (len(idx[0]))
                    slots[i] = k
                    i = i + 1
                else:
                    prod[k] = np.infty
        else:
            for k in np.arange(K1, K):
                idx = np.where(ks == k)
                if len(idx[0]) != 0:
                    prod[k] = sum(data[idx[0]] * data[idx[1]]) / (len(idx[0]))
                    slots[i - 1] = k
                    i = i + 1
                else:
                    prod[k] = np.infty
            np.trim_zeros(prod, trim='b')

        slots = np.trim_zeros(slots, trim='b')
        return prod / prod[0], np.int64(slots).flatten()

    def start_conditions(self, magnitude, time, T):
        N = len(time)

        if T is None:
            deltaT = time[1:] - time[:-1]
            sorted_deltaT = np.sort(deltaT)
            T = sorted_deltaT[int(N * 0.05)+1]

        K = 100

        SAC, slots = self.slotted_autocorrelation(magnitude, time, T, K)
        SAC2 = SAC[slots]

        return T, K, slots, SAC2

    def fit(self, magnitude, time, T):
        T, K, slots, SAC2 = self.start_conditions(magnitude, time, T)

        k = next((index for index, value in
                 enumerate(SAC2) if value < np.exp(-1)), None)

        while k is None:
            K = K + K
            if K > (np.max(time) - np.min(time)) / T:
                break
            else:
                SAC, slots = self.slotted_autocorrelation(
                    magnitude, time, T, K, second_round=True, K1=K/2)
                SAC2 = SAC[slots]
                k = next((index for index, value in
                         enumerate(SAC2) if value < np.exp(-1)), None)
        return slots[k] * T


class StetsonKAC(Extractor):

    data = ['magnitude', 'time', 'error']
    features = ["StetsonK_AC"]

    def fit(self, magnitude, time, error):
        sal = SlottedA_length(self.space)
        autocor_vector = sal.start_conditions(
            magnitude, time, **sal.params)[-1]

        N_autocor = len(autocor_vector)
        sigmap = (np.sqrt(N_autocor * 1.0 / (N_autocor - 1)) *
                  (autocor_vector - np.mean(autocor_vector)) /
                  np.std(autocor_vector))

        K = (1 / np.sqrt(N_autocor * 1.0) *
             np.sum(np.abs(sigmap)) / np.sqrt(np.sum(sigmap ** 2)))

        return K


class StetsonL(Extractor):

    data = ['aligned_magnitude', 'aligned_magnitude2',
            'aligned_error', 'aligned_error2']
    features = ["StetsonL"]

    def fit(self, aligned_magnitude, aligned_magnitude2,
            aligned_error, aligned_error2):
        magnitude, magnitude2 = aligned_magnitude, aligned_magnitude2
        error, error2 = aligned_error, aligned_error2

        N = len(magnitude)

        mean_mag = (np.sum(magnitude/(error*error)) /
                    np.sum(1.0 / (error * error)))
        mean_mag2 = (np.sum(magnitude2/(error2*error2)) /
                     np.sum(1.0 / (error2 * error2)))

        sigmap = (np.sqrt(N * 1.0 / (N - 1)) *
                  (magnitude[:N] - mean_mag) /
                  error)

        sigmaq = (np.sqrt(N * 1.0 / (N - 1)) *
                  (magnitude2[:N] - mean_mag2) /
                  error2)
        sigma_i = sigmap * sigmaq

        J = (1.0 / len(sigma_i) *
             np.sum(np.sign(sigma_i) * np.sqrt(np.abs(sigma_i))))

        K = (1 / np.sqrt(N * 1.0) *
             np.sum(np.abs(sigma_i)) / np.sqrt(np.sum(sigma_i ** 2)))

        return J * K / 0.798


class Con(Extractor):
    """Index introduced for selection of variable starts from OGLE database.


    To calculate Con, we counted the number of three consecutive measurements
    that are out of 2sigma range, and normalized by N-2
    Pavlos not happy
    """
    data = ['magnitude']
    features = ["Con"]
    params = {"consecutiveStar": 3}

    def fit(self, magnitude, consecutiveStar):

        N = len(magnitude)
        if N < consecutiveStar:
            return 0
        sigma = np.std(magnitude)
        m = np.mean(magnitude)
        count = 0

        for i in xrange(N - consecutiveStar + 1):
            flag = 0
            for j in xrange(consecutiveStar):
                if(magnitude[i + j] > m + 2 * sigma or
                   magnitude[i + j] < m - 2 * sigma):
                    flag = 1
                else:
                    flag = 0
                    break
            if flag:
                count = count + 1
        return count * 1.0 / (N - consecutiveStar + 1)


class Color(Extractor):
    """Average color for each MACHO lightcurve
    mean(B1) - mean(B2)
    """
    data = ['magnitude', 'time', 'magnitude2']
    features = ["Color"]

    def fit(self, magnitude, magnitude2):
        return np.mean(magnitude) - np.mean(magnitude2)


class Beyond1Std(Extractor):
    """Percentage of points beyond one st. dev. from the weighted
    (by photometric errors) mean
    """

    data = ['magnitude', 'error']
    features = ["Beyond1Std"]

    def fit(self, magnitude, error):
        n = len(magnitude)

        weighted_mean = np.average(magnitude, weights=1 / error ** 2)

        # Standard deviation with respect to the weighted mean

        var = sum((magnitude - weighted_mean) ** 2)
        std = np.sqrt((1.0 / (n - 1)) * var)

        count = np.sum(np.logical_or(magnitude > weighted_mean + std,
                                     magnitude < weighted_mean - std))

        return float(count) / n


class SmallKurtosis(Extractor):
    """Small sample kurtosis of the magnitudes.

    See http://www.xycoon.com/peakedness_small_sample_test_1.htm
    """

    data = ['magnitude']
    features = ["SmallKurtosis"]

    def fit(self, magnitude):
        n = len(magnitude)
        mean = np.mean(magnitude)
        std = np.std(magnitude)

        S = sum(((magnitude - mean) / std) ** 4)

        c1 = float(n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))
        c2 = float(3 * (n - 1) ** 2) / ((n - 2) * (n - 3))

        return c1 * S - c2


class Std(Extractor):
    """Standard deviation of the magnitudes"""

    data = ['magnitude']
    features = ["Std"]

    def fit(self, magnitude):
        return np.std(magnitude)


class Skew(Extractor):
    """Skewness of the magnitudes"""

    data = ['magnitude']
    features = ["Skew"]

    def fit(self, magnitude):
        return stats.skew(magnitude)


class StetsonJ(Extractor):
    """Stetson (1996) variability index, a robust standard deviation"""

    data = ['aligned_magnitude', 'aligned_magnitude2',
            'aligned_error', 'aligned_error2']
    features = ["StetsonJ"]

    def fit(self, aligned_magnitude, aligned_magnitude2,
            aligned_error, aligned_error2):

        N = len(aligned_magnitude)

        mean_mag = (np.sum(aligned_magnitude/(aligned_error*aligned_error)) /
                    np.sum(1.0 / (aligned_error * aligned_error)))

        mean_mag2 = (
            np.sum(aligned_magnitude2 / (aligned_error2*aligned_error2)) /
            np.sum(1.0 / (aligned_error2 * aligned_error2)))

        sigmap = (np.sqrt(N * 1.0 / (N - 1)) *
                  (aligned_magnitude[:N] - mean_mag) /
                  aligned_error)
        sigmaq = (np.sqrt(N * 1.0 / (N - 1)) *
                  (aligned_magnitude2[:N] - mean_mag2) /
                  aligned_error2)
        sigma_i = sigmap * sigmaq

        J = (1.0 / len(sigma_i) * np.sum(np.sign(sigma_i) *
             np.sqrt(np.abs(sigma_i))))

        return J


class MaxSlope(Extractor):
    """
    Examining successive (time-sorted) magnitudes, the maximal first difference
    (value of delta magnitude over delta time)
    """

    data = ['magnitude', 'time']
    features = ["MaxSlope"]

    def fit(self, magnitude, time):
        slope = np.abs(magnitude[1:] - magnitude[:-1]) / (time[1:] - time[:-1])
        np.max(slope)

        return np.max(slope)


class MedianAbsDev(Extractor):

    data = ['magnitude']
    features = ["MedianAbsDev"]

    def fit(self, magnitude):
        median = np.median(magnitude)
        devs = (abs(magnitude - median))
        return np.median(devs)


class MedianBRP(Extractor):
    """Median buffer range percentage

    Fraction (<= 1) of photometric points within amplitude/10
    of the median magnitude
    """

    data = ['magnitude']
    features = ["MedianBRP"]

    def fit(self, magnitude):
        median = np.median(magnitude)
        amplitude = (np.max(magnitude) - np.min(magnitude)) / 10
        n = len(magnitude)

        count = np.sum(np.logical_and(magnitude < median + amplitude,
                                      magnitude > median - amplitude))

        return float(count) / n


class PairSlopeTrend(Extractor):
    """
    Considering the last 30 (time-sorted) measurements of source magnitude,
    the fraction of increasing first differences minus the fraction of
    decreasing first differences.
    """
    data = ['magnitude']
    features = ["PairSlopeTrend"]

    def fit(self, magnitude):
        data_last = magnitude[-30:]

        return (float(len(np.where(np.diff(data_last) > 0)[0]) -
                len(np.where(np.diff(data_last) <= 0)[0])) / 30)


class FluxPercentileRatioMid20(Extractor):

    data = ['magnitude']
    features = ["FluxPercentileRatioMid20"]

    def fit(self, magnitude):
        sorted_data = np.sort(magnitude)
        lc_length = len(sorted_data)

        F_60_index = math.ceil(0.60 * lc_length)
        F_40_index = math.ceil(0.40 * lc_length)
        F_5_index = math.ceil(0.05 * lc_length)
        F_95_index = math.ceil(0.95 * lc_length)

        F_40_60 = sorted_data[F_60_index] - sorted_data[F_40_index]
        F_5_95 = sorted_data[F_95_index] - sorted_data[F_5_index]
        F_mid20 = F_40_60 / F_5_95

        return F_mid20


class FluxPercentileRatioMid35(Extractor):

    data = ['magnitude']
    features = ["FluxPercentileRatioMid35"]

    def fit(self, magnitude):
        sorted_data = np.sort(magnitude)
        lc_length = len(sorted_data)

        F_325_index = math.ceil(0.325 * lc_length)
        F_675_index = math.ceil(0.675 * lc_length)
        F_5_index = math.ceil(0.05 * lc_length)
        F_95_index = math.ceil(0.95 * lc_length)

        F_325_675 = sorted_data[F_675_index] - sorted_data[F_325_index]
        F_5_95 = sorted_data[F_95_index] - sorted_data[F_5_index]
        F_mid35 = F_325_675 / F_5_95

        return F_mid35


class FluxPercentileRatioMid50(Extractor):

    data = ['magnitude']
    features = ["FluxPercentileRatioMid50"]

    def fit(self, magnitude):
        sorted_data = np.sort(magnitude)
        lc_length = len(sorted_data)

        F_25_index = math.ceil(0.25 * lc_length)
        F_75_index = math.ceil(0.75 * lc_length)
        F_5_index = math.ceil(0.05 * lc_length)
        F_95_index = math.ceil(0.95 * lc_length)

        F_25_75 = sorted_data[F_75_index] - sorted_data[F_25_index]
        F_5_95 = sorted_data[F_95_index] - sorted_data[F_5_index]
        F_mid50 = F_25_75 / F_5_95

        return F_mid50


class FluxPercentileRatioMid65(Extractor):

    data = ['magnitude']
    features = ["FluxPercentileRatioMid65"]

    def fit(self, magnitude):
        sorted_data = np.sort(magnitude)
        lc_length = len(sorted_data)

        F_175_index = math.ceil(0.175 * lc_length)
        F_825_index = math.ceil(0.825 * lc_length)
        F_5_index = math.ceil(0.05 * lc_length)
        F_95_index = math.ceil(0.95 * lc_length)

        F_175_825 = sorted_data[F_825_index] - sorted_data[F_175_index]
        F_5_95 = sorted_data[F_95_index] - sorted_data[F_5_index]
        F_mid65 = F_175_825 / F_5_95

        return F_mid65


class FluxPercentileRatioMid80(Extractor):

    data = ['magnitude']
    features = ["FluxPercentileRatioMid80"]

    def fit(self, magnitude):
        sorted_data = np.sort(magnitude)
        lc_length = len(sorted_data)

        F_10_index = math.ceil(0.10 * lc_length)
        F_90_index = math.ceil(0.90 * lc_length)
        F_5_index = math.ceil(0.05 * lc_length)
        F_95_index = math.ceil(0.95 * lc_length)

        F_10_90 = sorted_data[F_90_index] - sorted_data[F_10_index]
        F_5_95 = sorted_data[F_95_index] - sorted_data[F_5_index]
        F_mid80 = F_10_90 / F_5_95

        return F_mid80


class PercentDifferenceFluxPercentile(Extractor):

    data = ['magnitude']
    features = ["PercentDifferenceFluxPercentile"]

    def fit(self, magnitude):
        median_data = np.median(magnitude)

        sorted_data = np.sort(magnitude)
        lc_length = len(sorted_data)
        F_5_index = math.ceil(0.05 * lc_length)
        F_95_index = math.ceil(0.95 * lc_length)
        F_5_95 = sorted_data[F_95_index] - sorted_data[F_5_index]

        percent_difference = F_5_95 / median_data

        return percent_difference


class PercentAmplitude(Extractor):

    data = ['magnitude']
    features = ["PercentAmplitude"]

    def fit(self, magnitude):
        median_data = np.median(magnitude)
        distance_median = np.abs(magnitude - median_data)
        max_distance = np.max(distance_median)

        percent_amplitude = max_distance / median_data

        return percent_amplitude


class LinearTrend(Extractor):

    data = ['magnitude', 'time']
    features = ["LinearTrend"]

    def fit(self, magnitude, time):
        regression_slope = stats.linregress(time, magnitude)[0]
        return regression_slope


class EtaColor(Extractor):

    data = ['aligned_magnitude', 'aligned_time', 'aligned_magnitude2']
    features = ["Eta_color"]

    def fit(self, aligned_magnitude, aligned_time, aligned_magnitude2):
        N = len(aligned_magnitude)
        B_Rdata = aligned_magnitude - aligned_magnitude2

        w = 1.0 / np.power(aligned_time[1:] - aligned_time[:-1], 2)
        w_mean = np.mean(w)

        N = len(aligned_time)
        sigma2 = np.var(B_Rdata)

        S1 = sum(w * (B_Rdata[1:] - B_Rdata[:-1]) ** 2)
        S2 = sum(w)

        eta_B_R = (w_mean * np.power(aligned_time[N - 1] -
                   aligned_time[0], 2) * S1 / (sigma2 * S2 * N ** 2))

        return eta_B_R


class Eta_e(Extractor):

    data = ['magnitude', 'time']
    features = ["Eta_e"]

    def fit(self, magnitude, time):
        w = 1.0 / np.power(np.subtract(time[1:], time[:-1]), 2)
        w_mean = np.mean(w)

        N = len(time)
        sigma2 = np.var(magnitude)

        S1 = sum(w * (magnitude[1:] - magnitude[:-1]) ** 2)
        S2 = sum(w)

        eta_e = (w_mean * np.power(time[N - 1] -
                 time[0], 2) * S1 / (sigma2 * S2 * N ** 2))

        return eta_e


class Mean(Extractor):

    data = ['magnitude']
    features = ["Mean"]

    def fit(self, magnitude):
        B_mean = np.mean(magnitude)
        return B_mean


class Q31(Extractor):

    data = ['magnitude']
    features = ["Q31"]

    def fit(self, magnitude):
        return np.percentile(magnitude, 75) - np.percentile(magnitude, 25)


class Q31Color(Extractor):

    data = ['aligned_magnitude', 'aligned_magnitude2']
    features = ["Q31_color"]

    def fit(self, aligned_magnitude, aligned_magnitude2):
        N = len(aligned_magnitude)
        b_r = aligned_magnitude[:N] - aligned_magnitude2[:N]

        return np.percentile(b_r, 75) - np.percentile(b_r, 25)


class AndersonDarling(Extractor):

    data = ['magnitude']
    features = ["AndersonDarling"]

    def fit(self, magnitude):
        ander = stats.anderson(magnitude)[0]
        return 1 / (1.0 + np.exp(-10 * (ander - 0.3)))


class LombScargle(Extractor):

    data = ['magnitude', 'time']
    features = ["PeriodLS", "Period_fit", "Psi_CS", "Psi_eta"]
    params = {"ofac": 6.}

    def _compute_ls(self, magnitude, time, ofac):
        fx, fy, nout, jmax, prob = lomb.fasper(time, magnitude, ofac, 100.)
        period = fx[jmax]
        T = 1.0 / period
        new_time = np.mod(time, 2 * T) / (2 * T)

        return T, new_time, prob, period

    def _compute_cs(self, folded_data, N):
        sigma = np.std(folded_data)
        m = np.mean(folded_data)
        s = np.cumsum(folded_data - m) * 1.0 / (N * sigma)
        R = np.max(s) - np.min(s)
        return R

    def _compute_eta(self, folded_data, N):
        sigma2 = np.var(folded_data)
        Psi_eta = (1.0 / ((N - 1) * sigma2) *
                   np.sum(np.power(folded_data[1:] - folded_data[:-1], 2)))
        return Psi_eta

    def fit(self, magnitude, time, ofac):
        T, new_time, prob, period = self._compute_ls(magnitude, time, ofac)

        folded_data = magnitude[np.argsort(new_time)]
        N = len(folded_data)

        R = self._compute_cs(folded_data, N)
        Psi_eta = self._compute_eta(folded_data, N)

        return T, prob, R, Psi_eta


class CAR(Extractor):

    data = ['magnitude', 'time', 'error']
    features = ["CAR_sigma", "CAR_tau", "CAR_mean"]

    def _CAR_Like(self, parameters, t, x, error_vars):

        sigma = parameters[0]
        tau = parameters[1]

        b = np.mean(x) / tau
        epsilon = 1e-300
        cte_neg = -np.infty
        num_datos = np.size(x)

        Omega, x_hat, a, x_ast = [], [], [], []

        Omega.append((tau * (sigma ** 2)) / 2.)
        x_hat.append(0.)
        a.append(0.)
        x_ast.append(x[0] - b * tau)

        loglik = 0.

        for i in range(1, num_datos):

            a_new = np.exp(-(t[i] - t[i - 1]) / tau)
            x_ast.append(x[i] - b * tau)
            x_hat.append(
                a_new * x_hat[i - 1] +
                (a_new * Omega[i - 1] / (Omega[i - 1] + error_vars[i - 1])) *
                (x_ast[i - 1] - x_hat[i - 1]))

            Omega.append(
                Omega[0] * (1 - (a_new ** 2)) + ((a_new ** 2)) * Omega[i - 1] *
                (1 - (Omega[i - 1] / (Omega[i - 1] + error_vars[i - 1]))))

            loglik_inter = np.log(
                ((2 * np.pi * (Omega[i] + error_vars[i])) ** -0.5) *
                (np.exp(-0.5 * (((x_hat[i] - x_ast[i]) ** 2) /
                 (Omega[i] + error_vars[i]))) + epsilon))

            loglik = loglik + loglik_inter

            if(loglik <= cte_neg):
                print('CAR loglikelihood to inf')
                return None

        # the minus one is to perfor maximization using the minimize function
        return -loglik

    def _calculate_CAR(self, time, magnitude, error):
        N = len(magnitude)
        magnitude = magnitude.reshape((N, 1))
        time = time.reshape((N, 1))
        error = error.reshape((N, 1)) ** 2

        x0 = [10, 0.5]
        bnds = ((0, 100), (0, 100))
        res = minimize(self._CAR_Like, x0, args=(time, magnitude, error),
                       method='nelder-mead', bounds=bnds)
        sigma, tau = res.x[0], res.x[1]
        return sigma, tau

    def fit(self, magnitude, time, error):
        sigma, tau = self._calculate_CAR(time, magnitude, error)
        mean = np.mean(magnitude) / tau
        return sigma, tau, mean


class FourierComponents(Extractor):

    data = ['magnitude', 'time']
    features = ['Freq1_harmonics_amplitude_0',
                'Freq1_harmonics_amplitude_1',
                'Freq1_harmonics_amplitude_2',
                'Freq1_harmonics_amplitude_3',
                'Freq2_harmonics_amplitude_0',
                'Freq2_harmonics_amplitude_1',
                'Freq2_harmonics_amplitude_2',
                'Freq2_harmonics_amplitude_3',
                'Freq3_harmonics_amplitude_0',
                'Freq3_harmonics_amplitude_1',
                'Freq3_harmonics_amplitude_2',
                'Freq3_harmonics_amplitude_3',
                'Freq1_harmonics_rel_phase_0',
                'Freq1_harmonics_rel_phase_1',
                'Freq1_harmonics_rel_phase_2',
                'Freq1_harmonics_rel_phase_3',
                'Freq2_harmonics_rel_phase_0',
                'Freq2_harmonics_rel_phase_1',
                'Freq2_harmonics_rel_phase_2',
                'Freq2_harmonics_rel_phase_3',
                'Freq3_harmonics_rel_phase_0',
                'Freq3_harmonics_rel_phase_1',
                'Freq3_harmonics_rel_phase_2',
                'Freq3_harmonics_rel_phase_3']

    def _model(self, x, a, b, c, Freq):
        return (a * np.sin(2 * np.pi * Freq * x) +
                b * np.cos(2 * np.pi * Freq * x) + c)

    def _yfunc_maker(self, Freq):
        def func(x, a, b, c):
            return (a * np.sin(2 * np.pi * Freq * x) +
                    b * np.cos(2 * np.pi * Freq * x) + c)
        return func

    def _compoenents(self, magnitude, time):
        time = time - np.min(time)
        A, PH, scaledPH = [], [], []
        for i in range(3):

            wk1, wk2, nout, jmax, prob = lomb.fasper(time, magnitude, 6., 100.)

            fundamental_Freq = wk1[jmax]
            Atemp, PHtemp, popts = [], [], []

            for j in range(4):
                function_to_fit = self._yfunc_maker((j + 1) * fundamental_Freq)
                popt, pcov = curve_fit(function_to_fit, time, magnitude)
                Atemp.append(np.sqrt(popt[0] ** 2 + popt[1] ** 2))
                PHtemp.append(np.arctan(popt[1] / popt[0]))
                popts.append(popt)

            A.append(Atemp)
            PH.append(PHtemp)

            for j in range(4):
                model = self._model(
                    time, popts[j][0], popts[j][1],
                    popts[j][2], (j+1) * fundamental_Freq)
                magnitude = np.array(magnitude) - model

        for ph in PH:
            scaledPH.append(np.array(ph) - ph[0])

    def fit(self, magnitude, time):
        A, PH, sPH = self._components(magnitude, time)
        freq1_aplitudes = [A[0][0], A[0][1], A[0][2], A[0][3]]
        freq2_aplitudes = [A[1][0], A[1][1], A[1][2], A[1][3]]
        freq3_aplitudes = [A[2][0], A[2][1], A[2][2], A[2][3]]

        freq1_phases = [sPH[0][0], sPH[0][1], sPH[0][2], sPH[0][3]]
        freq2_phases = [sPH[1][0], sPH[1][1], sPH[1][2], sPH[1][3]]
        freq3_phases = [sPH[2][0], sPH[2][1], sPH[2][2], sPH[2][3]]

        return (freq1_aplitudes + freq2_aplitudes + freq3_aplitudes +
                freq1_phases + freq2_phases + freq3_phases)


class Gskew(Extractor):
    """Median-based measure of the skew"""

    data = ['magnitude']
    features = ["Gskew"]

    def fit(self, magnitude):
        median_mag = np.median(magnitude)
        F_3_value = np.percentile(magnitude, 3)
        F_97_value = np.percentile(magnitude, 97)

        return (np.median(magnitude[magnitude <= F_3_value]) +
                np.median(magnitude[magnitude >= F_97_value]) - 2 * median_mag)


class StructureFunctions(Extractor):

    data = ['magnitude', 'time']
    features = ["StructureFunction_index_21",
                "StructureFunction_index_31",
                "StructureFunction_index_32"]

    def fit(self, magnitude, time):
        Nsf, Np = 100, 100
        sf1, sf2, sf3 = np.zeros(Nsf), np.zeros(Nsf), np.zeros(Nsf)
        f = interp1d(time, magnitude)

        time_int = np.linspace(np.min(time), np.max(time), Np)
        mag_int = f(time_int)

        for tau in np.arange(1, Nsf):
            sf1[tau-1] = np.mean(
                np.power(np.abs(mag_int[0:Np-tau] - mag_int[tau:Np]), 1.0))
            sf2[tau-1] = np.mean(
                np.abs(np.power(
                    np.abs(mag_int[0:Np-tau] - mag_int[tau:Np]), 2.0)))
            sf3[tau-1] = np.mean(
                np.abs(np.power(
                    np.abs(mag_int[0:Np-tau] - mag_int[tau:Np]), 3.0)))
        sf1_log = np.log10(np.trim_zeros(sf1))
        sf2_log = np.log10(np.trim_zeros(sf2))
        sf3_log = np.log10(np.trim_zeros(sf3))

        m_21, b_21 = np.polyfit(sf1_log, sf2_log, 1)
        m_31, b_31 = np.polyfit(sf1_log, sf3_log, 1)
        m_32, b_32 = np.polyfit(sf2_log, sf3_log, 1)

        return m_21, m_31, m_32


# =============================================================================
# REGISTERS
# =============================================================================

for cls in Extractor.__subclasses__():
    register_extractor(cls)
del cls
