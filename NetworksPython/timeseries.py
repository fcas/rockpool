###
# timeseries.py - Classes to manage time series
###

import numpy as np
import scipy.interpolate as spint
from warnings import warn
import copy
from typing import Union, List, Tuple, Optional, TypeVar, Iterable
import collections
import matplotlib as mpl
from matplotlib import pyplot as plt
import holoviews as hv

# - Define exports
__all__ = [
    "TimeSeries",
    "set_plotting_backend",
    "get_plotting_backend",
    "TSEvent",
    "TSContinuous",
]

# - Type alias for array-like objects and for yet undefined objects
ArrayLike = Union[np.ndarray, List, Tuple]
TSType = TypeVar("TimeSeries")
TSEventType = TypeVar("TSEvent")
TSContType = TypeVar("TSContinuous")

### -- Code for setting plotting backend

__bUseHoloviews = False
__bUseMatplotlib = False


# - Absolute tolerance, e.g. for comparing float values
fTolAbs = 1e-9


def set_plotting_backend(backend: Union[str, None]):
    global __bUseHoloviews
    global __bUseMatplotlib
    if backend in ("holoviews", "holo", "Holoviews", "HoloViews", "hv"):
        __bUseHoloviews = True
        __bUseMatplotlib = False

    elif backend in ("matplotlib", "mpl", "mp", "pyplot", "plt"):
        __bUseHoloviews = False
        __bUseMatplotlib = True

    elif backend is None:
        __bUseHoloviews = False
        __bUseMatplotlib = False

    else:
        raise ValueError("Plotting backend not recognized.")


def get_plotting_backend():
    return __bUseHoloviews, __bUseMatplotlib


def _extend_periodic_times(t_start: float, t_stop: float, series: TSType) -> np.ndarray:
    # TODO: docstring
    # - Repeat events sufficiently often
    # Number of additional required repetitions to append before and after
    num_reps_after = (
        int(np.ceil((t_stop - series.t_start) / series.duration))
        if t_stop > series.t_stop
        else 1
    )
    num_reps_before = (
        int(np.ceil((series.t_start - t_start) / series.duration))
        if t_start < series.t_start
        else 0
    )
    num_reps_total = num_reps_before + num_reps_after
    # - Correct times so they extend over the prolongued period and do not repeat
    # Enumerate periods so that originally defined period is 0
    periods = np.arange(num_reps_total) - num_reps_before
    correct_periods = series.duration * np.repeat(periods, series.times.size)
    return np.tile(series.times, num_reps_total) + correct_periods


## - Set default plotting backend
set_plotting_backend("matplotlib")


## - Convenience method to return a nan array
def full_nan(vnShape: Union[tuple, int]):
    a = np.empty(vnShape)
    a.fill(np.nan)
    return a


### --- TimeSeries base class


class TimeSeries:
    """
    TimeSeries - Class represent a continuous or event-based time series
    """

    def __init__(
        self,
        times: ArrayLike,
        periodic: bool = False,
        t_start: Optional[float] = None,
        t_stop: Optional[float] = None,
        name: str = "unnamed",
    ):
        """
        TimeSeries - Class represent a continuous or event-based time series

        :param times:     [Tx1] vector of time samples
        :param periodic:       bool: Treat the time series as periodic around the end points. Default: False
        :param t_start:          float: If not None, the series start time is t_start, otherwise times[0]
        :param t_stop:           float: If not None, the series stop time is t_stop, otherwise times[-1]
        :param name:         str: Name of the TimeSeries object. Default: `unnamed`
        """

        # - Convert time trace to numpy arrays
        times = np.atleast_1d(times).flatten().astype(float)

        if (np.diff(times) < 0).any():
            raise ValueError(
                f"TimeSeries `{name}`: The time trace must be not decreasing"
            )

        # - Assign attributes
        self._times = times
        self.periodic = periodic
        self.name = name
        self.t_start = (
            (0 if np.size(times) == 0 else times[0]) if t_start is None else t_start
        )
        self.t_stop = (
            (0 if np.size(times) == 0 else times[-1]) if t_stop is None else t_stop
        )

    def delay(self, offset: Union[int, float], inplace: bool = False) -> TSType:
        """
        delay - Return a copy of self that is delayed by an offset.
                For delaying self, use ".times += ..." instead.

        :param tOffset:    Time offset
        :param inplace:    Conduct operation in-place (Default: False; create a copy)
        :return: New TimeSeries, delayed
        """
        if not inplace:
            series = self.copy()
        else:
            series = self

        # - Store previous t_start and t_stop
        t_start_old = series.t_start
        t_stop_old = series.t_stop

        # - Shift time trace
        if not self.isempty():
            series.times += offset
        # - Shift t_start and t_stop
        series._t_start = t_start_old + offset
        series._t_stop = t_stop_old + offset

        return series

    def isempty(self):
        """
        isempty() - Is this TimeSeries object empty?

        :return: bool True -> The TimeSeries object contains no samples
        """
        return np.size(self.times) == 0

    def print(self):
        """print - Print an overview of the time series."""
        print(self.__repr__())

    def copy(self) -> TSType:
        """
        copy() - Return a deep copy of this time series
        :return: copy of `self`
        """
        return copy.deepcopy(self)

    def _modulo_period(
        self, times: Union[ArrayLike, float, int]
    ) -> Union[ArrayLike, float, int]:
        """_modulo_period - Calculate provided times modulo `self.duration`"""
        return self.t_start + np.modulo(times - self.t_start, self.duration)

    @property
    def times(self):
        return self._times

    @times.setter
    def times(self, new_times: ArrayLike):
        # - Check time trace for correct size
        if np.size(new_times) != np.size(self._times):
            raise ValueError(
                f"TSContinuous `{self.name}`: "
                + "New time trace must have the same number of elements as the original trace."
            )

        # - Make sure time trace is sorted
        if (np.diff(new_times) < 0).any():
            raise ValueError(
                f"TSContinuous `{self.name}`: "
                + "The time trace must be sorted and not decreasing"
            )

        # - Store new time trace
        self._times = np.atleast_1d(new_times).flatten().astype(float)

        if np.size(self._times) > 0:
            # - Fix t_start and t_stop
            self._t_start = min(self._t_start, new_times[0])
            self._t_stop = max(self._t_stop, new_times[-1])

    @property
    def t_start(self) -> float:
        """
        .t_start: float Start time
        """
        return self._t_start

    @t_start.setter
    def t_start(self, new_start):
        if np.size(self._times) == 0 or new_start <= self._times[0]:
            self._t_start = new_start
        else:
            raise ValueError(
                "TimeSeries `{}`: t_start must be less or equal to {}. It was {}.".format(
                    self.name, self._times[0], new_start
                )
            )

    @property
    def t_stop(self) -> float:
        """
        .t_stop: float Stop time
        """
        return self._t_stop

    @t_stop.setter
    def t_stop(self, new_stop):
        if np.size(self._times) == 0 or new_stop >= self._times[-1]:
            self._t_stop = new_stop
        else:
            raise ValueError(
                "TimeSeries `{}`: t_stop must be greater or equal to {}.".format(
                    self.name, self._times[-1]
                )
            )

    @property
    def duration(self) -> float:
        """
        .duration: float Duration of TimeSeries
        """
        return self._t_stop - self._t_start


### --- Continuous-valued time series


class TSContinuous(TimeSeries):
    """
    TSContinuous - Class represent a multi-series time series, with temporal interpolation
                   and periodicity supported
    """

    def __init__(
        self,
        times: ArrayLike = None,
        samples: ArrayLike = None,
        num_channels: int = None,
        periodic: bool = False,
        t_start: Optional[float] = None,
        t_stop: Optional[float] = None,
        name: str = "unnamed",
        interp_kind: str = "linear",
    ):
        """
        TSContinuous - Class represent a multi-series time series, with temporal interpolation and periodicity supported

        :param times:     [Tx1] vector of time samples
        :param samples:       [TxM] matrix of values corresponding to each time sample
        :param num_channels:  If `samples` is None, determines the number of channels of
                              `self`. Otherwise it has no effect at all.
        :param periodic:       bool: Treat the time series as periodic around the end points. Default: False
        :param t_start:          float: If not None, the series start time is t_start, otherwise times[0]
        :param t_stop:           float: If not None, the series stop time is t_stop, otherwise times[-1]
        :param name:         str: Name of the TSContinuous object. Default: `unnamed`
        :param interp_kind:   str: Specify the interpolation type. Default: 'linear'

        If the time series is not periodic (the default), then NaNs will be returned for any extrapolated values.
        """

        if times is None:
            times = np.array([])
        if samples is None:
            num_channels = 0 if num_channels is None else num_channels
            samples = np.zeros((0, num_channels))

        # - Convert everything to numpy arrays
        times = np.atleast_1d(times).flatten().astype(float)
        samples = np.atleast_1d(samples)

        # - Check arguments
        assert np.size(times) == samples.shape[0], (
            f"TSContinuous `{name}`: The number of time samples must be equal to the"
            " first dimension of `samples`"
        )
        assert np.all(
            np.diff(times) >= 0
        ), f"TSContinuous `{name}`: The time trace must be sorted and not decreasing"

        # - Initialize superclass
        super().__init__(
            times=times, periodic=periodic, t_start=t_start, t_stop=t_stop, name=name
        )

        # - Assign attributes
        self.interp_kind = interp_kind
        self.samples = samples.astype("float")

    ## -- Methods for plotting and printing

    def plot(
        self,
        times: Union[int, float, ArrayLike] = None,
        target: Union[mpl.axes.Axes, hv.Curve, hv.Overlay, None] = None,
        channels: Union[ArrayLike, int, None] = None,
        *args,
        **kwargs,
    ):
        """
        plot - Visualise a time series on a line plot

        :param times: Optional. Time base on which to plot. Default: time base of time series
        :param target:  Optional. Object to which plot will be added.
        :param channels:  Optional. Channels that are to be plotted.
        :param args, kwargs:  Optional arguments to pass to plotting function

        :return: Plot object. Either holoviews Layout, or matplotlib plot
        """
        if times is None:
            times = self.times
            samples = self.samples
        else:
            samples = self(times)
        if channels is not None:
            samples = samples[:, channels]

        if target is None:
            # - Get current plotting backend from global settings
            _use_holoviews, _use_matplotlib = get_plotting_backend()

            if _use_holoviews:
                if kwargs == {}:
                    vhCurves = [
                        hv.Curve((times, vfData)).redim(x="Time")
                        for vfData in samples.T
                    ]
                else:
                    vhCurves = [
                        hv.Curve((times, vfData))
                        .redim(x="Time")
                        .options(*args, **kwargs)
                        for vfData in samples.T
                    ]

                if len(vhCurves) > 1:
                    return hv.Overlay(vhCurves).relabel(group=self.name)
                else:
                    return vhCurves[0].relabel(self.name)

            elif _use_matplotlib:
                # - Add `self.name` as label only if a label is not already present
                kwargs["label"] = kwargs.get("label", self.name)
                return plt.plot(times, samples, **kwargs)

            else:
                raise RuntimeError(
                    f"TSContinuous: `{self.name}`: No plotting back-end detected."
                )

        else:
            # - Infer current plotting backend from type of `target`
            if isinstance(target, (hv.Curve, hv.Overlay)):
                if kwargs == {}:
                    for vfData in samples.T:
                        target *= hv.Curve((times, vfData)).redim(x="Time")
                else:
                    for vfData in samples.T:
                        target *= (
                            hv.Curve((times, vfData))
                            .redim(x="Time")
                            .options(*args, **kwargs)
                        )
                return target.relabel(group=self.name)
            elif isinstance(target, mpl.axes.Axes):
                # - Add `self.name` as label only if a label is not already present
                kwargs["label"] = kwargs.get("label", self.name)
                target.plot(times, samples, **kwargs)
                return target
            else:
                raise TypeError(
                    f"TSContinuous: `{self.name}`: Unrecognized type for `target`. "
                    + "It must be matplotlib Axes or holoviews Curve or Overlay."
                )

    def print(
        self,
        full: bool = False,
        num_first: int = 4,
        num_last: int = 4,
        limit_shorten: int = 10,
    ):
        """
        print - Print an overview of the time series and its values.

        :param full:           Print all samples of `self`, no matter how long it is
        :param limit_shorten:  Print shortened version of self if it comprises more
                               than `limit_shorten` time points and `full` is False
        :param num_first:      Shortened version of printout contains samples at first
                               `num_first` points in `self.times`
        :param num_last:       Shortened version of printout contains samples at last
                               `num_last` points in `self.times`
        """

        s = "\n"
        if len(self.times) <= 10 or full:
            summary = s.join(
                [
                    "{}: \t {}".format(t, samples)
                    for t, samples in zip(self.times, self.samples)
                ]
            )
        else:
            summary0 = s.join(
                [
                    "{}: \t {}".format(t, samples)
                    for t, samples in zip(
                        self.times[:num_first], self.samples[:num_first]
                    )
                ]
            )
            summary1 = s.join(
                [
                    "{}: \t {}".format(t, samples)
                    for t, samples in zip(
                        self.times[-num_last:],
                        self.samples[-num_last + int(self.periodic) :],
                    )
                ]
            )
            if self.periodic:
                summary1 += f"\n{self.times[-1]}: \t {self(self.times[-1])}"
                summary1 += "\n\t (...periodic...)"
            summary = summary0 + "\n\t...\n" + summary1
        print(self.__repr__() + "\n" + summary)

    def save(self, strPath: str):
        """
        save - Save TSContinuous as npz file using np.savez
        :param strPath:     str  Path to save file
        """
        np.savez(
            strPath,
            times=self.times,
            samples=self.samples,
            t_start=self.t_start,
            t_stop=self.t_stop,
            interp_kind=self.interp_kind,
            periodic=self.periodic,
            name=self.name,
            strType="TSContinuous",  # Indicate that this object is TSContinuous
        )
        missing_ending = strPath.split(".")[-1] != "npz"  # np.savez will add ending
        print(
            "TSContinuous `{}` has been stored in `{}`.".format(
                self.name, strPath + missing_ending * ".npz"
            )
        )

    ## -- Methods for finding and extracting data

    def contains(self, times: Union[int, float, ArrayLike]) -> bool:
        """
        contains - Does the time series contain the time range specified in the given time trace?

        :param times: Array-like containing time points
        :return:            boolean: All time points are contained within this time series
        """
        return (
            True
            if self.t_start <= np.min(times) and self.t_stop >= np.max(times)
            else False
        )

    def clip(
        self,
        t_start: Optional[float] = None,
        t_stop: Optional[float] = None,
        channels: Union[int, ArrayLike, None] = None,
        include_stop: bool = False,
        sample_limits: bool = True,
        inplace: bool = False,
    ) -> TSContType:
        """
        clip - Return a TSContinuous which is restricted to given time limits and only
               contains events of selected channels. If no time limits are provided,
               t_start and t_stop attributes will correspond to those.
               If `inplace` is True, modify `self` accordingly.
        clip - Clip a TimeSeries to data only within a new set of time bounds (exclusive end points)

        :param t_start:       Time from which on events are returned
        :param t_stop:        Time until which events are returned
        :param channels:      Channels of which events are returned
        :param include_stop:  If there are events with time t_stop include them or not.
        :param sample_limits: If True, make sure that a sample exists at `t_start` and, if
                              `include_stop` is True, at `t_stop`, as long as not both are None.
        :param inplace:       Conduct operation in-place (Default: False; create a copy)

        :return:
                clipped_series:     New TimeSeries clipped to bounds
        """
        # - Create a new time series, or modify this time series
        if not inplace:
            clipped_series = self.copy()
        else:
            clipped_series = self

        # - Select channels
        if channels is not None:
            clipped_series._samples = clipped_series._samples[:, channels]
            clipped_series._num_channels = clipped_series._samples.shape[1]

        # - Handle `None` time bounds
        if t_start is None and t_stop is None:
            # - Skip time clipping and return
            return clipped_series
        else:
            t_start: float = self.t_start if t_start is None else t_start
            t_stop: float = self.t_stop if t_stop is None else t_stop

        # - Ensure time bounds are sorted
        t_start, t_stop = sorted((t_start, t_stop))

        # - Handle periodic time series
        times_to_choose: np.ndarray = (
            _extend_periodic_times(t_start, t_stop, clipped_series)
            if clipped_series.periodic
            else clipped_series.times
        )

        # - Mark which times lie within bounds
        times_in_limits: np.ndarray = times_to_choose >= t_start
        times_in_limits[times_to_choose > t_stop] = True
        if include_stop:
            # - Include samples at time `t_stop`
            times_in_limits[times_to_choose == t_stop] = True
        # - Pick matching times
        times: np.ndarray = times_to_choose[times_in_limits]
        if sample_limits:
            add_start = times[0] > t_start
            add_stop = times[-1] < t_stop and include_stop
            # - Only generate new array once
            if add_start and add_stop:
                times = np.r_[t_start, times, t_stop]
            elif add_start:
                times = np.r_[t_start, times]
            elif add_stop:
                times = np.r_[times, t_stop]

        # - Sample at the chosen time points and return
        return clipped_series.resample(times, inplace=True)

    def resample(
        self, times: Union[int, float, ArrayLike], inplace: bool = False
    ) -> TSContType:
        """
        resample - Return a new time series sampled to the supplied time base

        :param times:     Array-like of T desired time points to resample
        :param inplace:    bool    Conduct operation in-place (Default: False; create a copy)
        :return:            TimeSeries object, resampled to new time base
        """
        if not inplace:
            resampled_series = self.copy()
        else:
            resampled_series = self

        # - Make sure `times` is array
        times = np.atleast_1d(times)

        # - Resample time series
        resampled_series._samples = self(times)
        resampled_series._times = times
        resampled_series._t_start = times[0]
        resampled_series._t_stop = times[-1]
        resampled_series.periodic = False
        resampled_series._create_interpolator()
        return resampled_series

    ## -- Methods for combining time series

    def merge(
        self,
        other_series: TSContType,
        remove_duplicates: bool = True,
        inplace: bool = False,
    ) -> TSContType:
        """
        merge - Merge another time series to this one, in time. Maintain
                each time series' time values and channel IDs.
        :param other_series:      TimeSeries that is merged to self
        :param remove_duplicates: If true, time points in other_series.times
                                  that are also in self.times are
                                  discarded. Otherwise they are included in
                                  the new time trace and come after the
                                  corresponding points of self.times.
        :param inplace:           Conduct operation in-place (Default: False; create a copy)
        :return:         The merged time series
        """

        # - Check other_series
        if not isinstance(other_series, TSContinuous):
            raise TypeError(
                f"TSContinuous `{self.name}`: "
                + "`other_series` must be a TSContinuous object."
            )

        if other_series.num_channels != self.num_channels:
            raise ValueError(
                f"TSContinuous `{self.name}`: `other_series` must include "
                f"the same number of traces ({self.num_channels})."
            )

        # - Create a new time series, or modify this time series
        if not inplace:
            merged_series = self.copy()
        else:
            merged_series = self

        # - If the other TimeSeries is empty, just return
        if other_series.isempty():
            return merged_series

        # - If remove_duplicates == True and time ranges overlap,  find and remove
        #   time points of other_series that are also included in self (assuming both
        #   TimeSeries have a sorted vTimeTrace)
        if remove_duplicates and not (
            self.t_start > other_series.t_stop or self.t_stop < other_series.t_start
        ):
            # Determine region of overlap
            overlap: np.ndarray = np.where(
                (self.times >= other_series.t_start)
                & (self.times <= other_series.t_stop)
            )[0]
            # Array of bools indicating which sampled time points of other_series do not occur in self
            is_unique = np.array(
                [(t != self.times[overlap]).all() for t in other_series.times]
            )
            # Time trace and samples to be merged into self
            times_other: np.ndarray = other_series.times[is_unique]
            samples_other: np.ndarray = other_series.samples[is_unique]
        else:
            times_other: np.ndarray = other_series.times
            samples_other: np.ndarray = other_series.samples

        # - Merge time traces and samples
        times_new: np.ndarray = np.concatenate((self._times, times_other))
        samples_new: np.ndarray = np.concatenate((self.samples, samples_other), axis=0)

        #  - Indices for sorting new time trace and samples. Use mergesort as stable sorting algorithm.
        viSorted: np.ndarray = np.argsort(times_new, kind="mergesort")

        # - Update data of new time series
        merged_series._times = times_new[viSorted]
        merged_series._samples = samples_new[viSorted]
        merged_series._t_start: float = min(self.t_start, other_series.t_start)
        merged_series._t_stop: float = max(self.t_stop, other_series.t_stop)

        # - Create new interpolator
        merged_series._create_interpolator()

        # - Return merged TS
        return merged_series

    def append_c(self, other_series: TSContType, inplace: bool = False) -> TSContType:
        """
        append() - Combine another time series into this one, along samples axis

        :param other_series: Another time series. Will be resampled to the time base of the called series object
        :param inplace:    bool    Conduct operation in-place (Default: False; create a copy)
        :return:        Current time series,
        """
        # - Check other_series
        if not isinstance(other_series, TSContinuous):
            raise TypeError(
                f"TSContinuous `{self.name}`: "
                + "`other_series` must be a TSContinuous object."
            )

        # - Resample other_series to own time base
        other_samples = other_series(self.times)

        # - Create a new time series, or modify this time series
        if not inplace:
            appended_series = self.copy()
        else:
            appended_series = self

        # - Combine samples
        appended_series.samples = np.concatenate(
            (np.atleast_2d(appended_series.samples), other_samples), 1
        )

        # - Create new interpolator
        appended_series._create_interpolator()

        # - Return appended TS
        return appended_series

    def append_t(
        self,
        other_series: TSContType,
        offset: Optional[float] = None,
        inplace: bool = False,
    ) -> TSContType:
        """
        append_t() - Append another time series to this one, in time

        :param other_series: Another time series. Will be tacked on to the end of the called series object
        :param offset:       If not None, defines distance between last sample of `self`
                             and first sample of `other_series`. Otherwise distance will
                             be median of all timestep sizes of `self.samples`.
        :param inplace:      Conduct operation in-place (Default: False; create a copy)
        :return: Time series containing current data, with other TS appended in time
        """

        # - Check other_series
        if not isinstance(other_series, TSContinuous):
            raise TypeError(
                f"TSContinuous `{self.name}`: "
                + "`other_series` must be a TSContinuous object."
            )

        # - Create a new time series, or modify this time series
        if not inplace:
            appended_series = self.copy()
        else:
            appended_series = self

        # - Concatenate time trace and samples
        appended_series._samples = np.concatenate(
            (appended_series.samples, other_series.samples), axis=0
        )

        if offset is None:
            # - If `self` is empty append new elements directly. Otherwise leafe space
            #   corresponding to median distance between time points in `self._times`.
            offset = np.median(np.diff(self._times)) if self.times.size > 0 else 0
        # - Time by which `other_series` has to be delayed
        delay = appended_series.t_stop + offset - other_series.t_start

        # - Let `self.merge` do the rest
        return self.merge(
            other_series.delay(delay), remove_duplicates=False, inplace=inplace
        )

    ## -- Internal methods

    def _create_interpolator(self):
        """
        _create_interpolator - Build an interpolator for the samples in this TimeSeries
        """
        if np.size(self.times) == 0:
            self.interp = lambda o: None
            return

        elif np.size(self.times) == 1:
            # - Replicate to avoid error in `interp1d`
            times = np.repeat(self.times, 2, axis=0)
            samples = np.repeat(self.samples, 2, axis=0)
        else:
            times = self._times
            samples = self._samples

        # - Construct interpolator
        self.interp = spint.interp1d(
            times,
            samples,
            kind=self.interp_kind,
            axis=0,
            assume_sorted=True,
            bounds_error=False,
        )

    def _interpolate(self, times: Union[int, float, ArrayLike]) -> np.ndarray:
        """
        _interpolate - Interpolate the time series to the provided time points

        :param times: np.ndarray of T desired interpolated time points
        :return:        np.ndarray of interpolated values. Will have the shape TxN
        """
        # - Enforce periodicity
        if self.periodic:
            times = (np.asarray(times) - self._t_start) % self.duration + self._t_start

        return np.reshape(self.interp(times), (-1, self.num_channels))

    def _compatible_shape(self, other_samples) -> np.ndarray:
        try:
            return np.broadcast_to(other_samples, self.samples.shape).copy()
        except ValueError:
            raise ValueError(
                f"TSContinuous `{self.name}`: Input data (shape {other_samples.shape})"
                f" could not be broadcast to samples shape ({self.samples.shape})."
            )

    ## -- Magic methods

    def __call__(self, times: Union[int, float, ArrayLike]):
        """
        ts(tTime1, tTime2, ...) - Interpolate the time series to the provided time points

        :param tTime: Scalar, list or np.array of T desired interpolated time points
        :return:      np.array of interpolated values. Will have the shape TxN
        """
        return self._interpolate(times)

    def __getitem__(self, indices: Union[ArrayLike, slice]) -> np.ndarray:
        """
        ts[tTime1, tTime2, ...] - Interpolate the time series to the provided time points
                                  or, if slice is provided between given limits with given
                                  step size.
        :param indices: Slice, scalar, list or np.array of T desired interpolated time points
        :return:        np.array of interpolated values. Will have the shape TxN
        """
        if isinstance(indices, slice):
            # - Use `self.clip`
            if indices.step is None:
                return self.clip(
                    t_start=indices.start,
                    t_stop=indices.stop,
                    inplace=False,
                    include_stop=False,
                )
            # - Prepare time points for `self.resample`
            else:
                t_start: float = (
                    self.t_start if indices.start is None else indices.start
                )
                t_stop: float = (self.t_stop if indices.stop is None else indices.stop)
                # - Determine time points at which series is sampled
                time_points: np.ndarray = np.arange(t_start, t_stop, indices.step)
                # - Make sure time points are within limits
                time_points = time_points[
                    np.logical_and(
                        time_points >= self.t_start, time_points < self.t_stop
                    )
                ]
                # - Invert order if step is negative
                if indices.step < 0:
                    time_points = time_points[::-1]
        else:
            time_points = indices

        return self.resample(time_points, inplace=False)

    def __repr__(self):
        """
        __repr__() - Return a string representation of this object
        :return: str String description
        """
        if self.isempty():
            return f"Empty TSContinuous object `{self.name}`"
        else:
            return "{}periodic TSContinuous object `{}` from t={} to {}. Shape: {}".format(
                int(not self.periodic) * "non-",
                self.__class__.__name__,
                self.name,
                self.t_start,
                self.t_stop,
                self.samples.shape,
            )

    ## -- Operator overloading

    # - Addition

    def __add__(self, other_samples):
        return self.copy().__iadd__(other_samples)

    def __radd__(self, other_samples):
        return self + other_samples

    def __iadd__(self, other_samples):
        if isinstance(other_samples, TSContinuous):
            other_samples = self._compatible_shape(other_samples(self.times))
        else:
            other_samples = self._compatible_shape(other_samples)

        # - Treat NaNs as zero
        is_nan_self = np.isnan(self.samples)
        is_nan_other = np.isnan(other_samples)
        self.samples[is_nan_self] = 0
        other_samples[is_nan_other] = 0

        # - Perform addition
        new_samples = self.samples + other_samples
        self.samples = new_samples

        # - Fill in nans
        self.samples[np.logical_and(is_nan_self, is_nan_other)] = np.nan

        return self

    # - Subtraction

    def __sub__(self, other_samples):
        return self.copy().__isub__(other_samples)

    def __rsub__(self, other_samples):
        return -(self - other_samples)

    def __isub__(self, other_samples):
        if isinstance(other_samples, TSContinuous):
            other_samples = self._compatible_shape(other_samples(self.times))
        else:
            other_samples = self._compatible_shape(other_samples)

        # - Treat NaNs as zero
        is_nan_self = np.isnan(self.samples)
        is_nan_other = np.isnan(other_samples)
        self.samples[is_nan_self] = 0
        other_samples[is_nan_other] = 0

        # - Perform subtraction
        self.samples -= other_samples

        # - Fill in nans
        self.samples[np.logical_and(is_nan_self, is_nan_other)] = np.nan

        return self

    # - Multiplication

    def __mul__(self, other_samples):
        return self.copy().__imul__(other_samples)

    def __rmul__(self, other_samples):
        return self * other_samples

    def __imul__(self, other_samples):
        if isinstance(other_samples, TSContinuous):
            other_samples = self._compatible_shape(other_samples(self.times))
        else:
            other_samples = self._compatible_shape(other_samples)

        # - Propagate NaNs
        is_nan_self = np.isnan(self.samples)
        is_nan_other = np.isnan(other_samples)

        # - Perform multiplication
        self.samples *= other_samples

        # - Fill in nans
        self.samples[np.logical_or(is_nan_self, is_nan_other)] = np.nan

        return self

    # - Division

    def __truediv__(self, other_samples):
        return self.copy().__itruediv__(other_samples)

    def __rtruediv__(self, other_samples):
        self_copy = self.copy()
        self_copy.samples = 1 / self_copy.samples
        return self_copy * other_samples

    def __itruediv__(self, other_samples):
        if isinstance(other_samples, TSContinuous):
            other_samples = self._compatible_shape(
                np.reshape(other_samples(self.times), (np.size(self.times), -1))
            )
        else:
            other_samples = self._compatible_shape(other_samples)

        # - Propagate NaNs
        is_nan_self = np.isnan(self.samples)
        is_nan_other = np.isnan(other_samples)

        # - Perform division
        self.samples /= other_samples

        # - Fill in nans
        self.samples[np.logical_or(is_nan_self, is_nan_other)] = np.nan

        # - Re-create interpolator
        self._create_interpolator()
        return self

    # - Floor division

    def __floordiv__(self, other_samples):
        return self.copy().__ifloordiv__(other_samples)

    def __rfloordiv__(self, other_samples):
        self_copy = self.copy()
        self_copy.samples = 1 / self_copy.samples
        return self_copy // (1 / other_samples)

    def __ifloordiv__(self, other_samples):
        if isinstance(other_samples, TSContinuous):
            other_samples = self._compatible_shape(other_samples(self.times))
        else:
            other_samples = self._compatible_shape(other_samples)

        # - Propagate NaNs
        is_nan_self = np.isnan(self.samples)
        is_nan_other = np.isnan(other_samples)

        # - Perform division
        self.samples //= other_samples

        # - Fill in nans
        self.samples[np.logical_or(is_nan_self, is_nan_other)] = np.nan

        return self

    # - Exponentiation

    def __pow__(self, exponent):
        return self.copy().__ipow__(exponent)

    def __rpow__(self, base):
        new_series = self.copy()

        base = new_series._compatible_shape(base)

        # - Propagate NaNs
        is_nan_self = np.isnan(new_series.samples)
        is_nan_other = np.isnan(base)

        # - Perform exponentiation
        new_series.samples = base ** new_series.samples

        # - Fill in nans
        new_series.samples[np.logical_or(is_nan_self, is_nan_other)] = np.nan

        return new_series

    def __ipow__(self, exponent):
        if isinstance(exponent, TSContinuous):
            exponent = self._compatible_shape(exponent(self.times))
        else:
            exponent = self._compatible_shape(exponent)

        # - Propagate NaNs
        is_nan_self = np.isnan(self.samples)
        is_nan_other = np.isnan(exponent)

        # - Perform exponentiation
        self.samples **= exponent

        # - Fill in nans
        self.samples[np.logical_or(is_nan_self, is_nan_other)] = np.nan

        return self

    # - Absolute

    def __abs__(self):
        self_copy = self.copy()
        self_copy.samples = np.abs(self_copy.samples)
        return self_copy

    # - Negative

    def __neg__(self):
        self_copy = self.copy()
        self_copy.samples = -self_copy.samples
        return self_copy

    ## -- Properties

    @property
    def samples(self):
        return self._samples

    @samples.setter
    def samples(self, new_samples: ArrayLike):
        # - Make sure that if assigned empty samples array, number of traces is implicityly
        #   with as second dimension of `new_samples`
        if np.size(new_samples) == 0 and np.ndim(new_samples) < 2:
            raise ValueError(
                f"TSContinuous `{self.name}`: "
                + "Empty samples object must be 2D to allow infering the number of channels."
            )

        # - Promote to 2d
        new_samples = np.atleast_2d(new_samples)

        # - Permit a one-dimensional sample input, promote to 2d
        if (new_samples.shape[0] == 1) and (np.size(self.times) > 1):
            new_samples = np.reshape(new_samples, (np.size(self.times), -1))

        # - Check samples for correct size
        if new_samples.shape[0] != np.size(self.times):
            raise ValueError(
                f"TSContinuous `{self.name}`: "
                + "New samples matrix must have the same number of samples as `.times`."
            )

        # - Store new time trace
        self._samples = new_samples

        # - Create a new interpolator
        self._create_interpolator()

    # - Extend setter of times to update interpolator
    @property
    def times(self):
        return super().times

    @times.setter
    def times(self, new_times: ArrayLike):
        super(TSContinuous, self.__class__).times.fset(self, new_times)
        # - Create a new interpolator
        self._create_interpolator()

    @property
    def num_traces(self):
        """num_traces - Synonymous to num_channels"""
        return self.samples.shape[1]

    @property
    def num_channels(self):
        """num_channels: int Number of channels (dimension of sample vectors) in this TimeSeries object"""
        return self.samples.shape[1]

    @property
    def max(self):
        return np.nanmax(self.samples)

    @property
    def min(self):
        return np.nanmin(self.samples)


### --- Event time series


class TSEvent(TimeSeries):
    def __init__(
        self,
        times: ArrayLike = None,
        channels: Union[int, ArrayLike] = None,
        periodic: bool = False,
        t_start: Optional[float] = None,
        t_stop: Optional[float] = None,
        name: str = None,
        num_channels: int = None,
    ):
        """
        TSEvent - Represent discrete events in time

        :param times:     np.array float Tx1 vector of event times
        :param channels:      np.array int Tx1 vector of event channels (Default: channel 0)

        :param periodic:       bool Is this a periodic TimeSeries (Default: False)

        :param t_start:          float: If not None, the series start time is t_start, otherwise times[0]
        :param t_stop:           float: If not None, the series stop time is t_stop, otherwise times[-1]

        :param name:         str Name of the time series (Default: None)

        :param num_channels:    int Total number of channels in the data source. If None,
                                    it is inferred from the max channel ID in channels
        """

        # - Default time trace: empty
        if times is None:
            times = np.array([])
        else:
            times = np.atleast_1d(times).flatten().astype(float)

        # - Default channel: zero
        if channels is None or np.size(channels) == 0:
            channels = np.zeros(np.size(times))
            nMinNumChannels = min(np.size(times), 1)
        # - Handle scalar channel
        elif isinstance(channels, int):
            nMinNumChannels = channels + 1
            channels = np.array([channels for _ in times])
        # - Array-like of channels
        else:
            if np.size(channels) != np.size(times):
                # - Make sure item sizes match
                raise ValueError(
                    f"TSEvent `{name}`: `channels` must have the same number of "
                    + "elements as `times`, be an integer or None."
                )
            else:
                nMinNumChannels = np.amax(channels) + 1

        if num_channels is None:
            # - Infer number of channels from maximum channel id in channels
            num_channels = nMinNumChannels
        else:
            if num_channels < nMinNumChannels:
                raise ValueError(
                    f"TSEvent `{name}`: num_channels must be None or greater than the highest channel ID."
                )

        # - Initialize superclass
        super().__init__(
            times=times, periodic=periodic, t_start=t_start, t_stop=t_stop, name=name
        )

        # - Store channels
        self.channels = np.array(channels, "int").flatten()

        # - Store total number of channels
        self._num_channels = int(num_channels)

    def print(
        self,
        full: bool = False,
        num_first: int = 4,
        num_last: int = 4,
        limit_shorten: int = 10,
    ):
        """
        print - Print an overview of the time series and its values.

        :param full:           Print all samples of `self`, no matter how long it is
        :param limit_shorten:  Print shortened version of self if it comprises more
                               than `limit_shorten` time points and `full` is False
        :param num_first:      Shortened version of printout contains samples at first
                               `num_first` points in `self.times`
        :param num_last:       Shortened version of printout contains samples at last
                               `num_last` points in `self.times`
        """

        s = "\n"
        if len(self.times) <= 10 or full:
            summary = s.join(
                [f"{t}: \t {ch}" for t, ch in zip(self.times, self.channels)]
            )
        else:
            summary0 = s.join(
                [
                    f"{t}: \t {ch}"
                    for t, ch in zip(self.times[:num_first], self.channels[:num_first])
                ]
            )
            summary1 = s.join(
                [
                    f"{t}: \t {ch}"
                    for t, ch in zip(self.times[-num_last:], self.channels[-num_last:])
                ]
            )
            summary = summary0 + "\n\t...\n" + summary1
        print(self.__repr__() + "\nTime \t Ch.-ID" + "\n" + summary)

    ## -- Methods for plotting and printing

    def plot(
        self,
        time_limits: Optional[Tuple[Optional[float], Optional[float]]] = None,
        target: Union[mpl.axes.Axes, hv.Scatter, hv.Overlay, None] = None,
        channels: Union[ArrayLike, int, None] = None,
        *args,
        **kwargs,
    ):
        """
        plot - Visualise a time series on a line plot

        :param time_limits: Optional. Tuple with times between which to plot
        :param target:  Optional. Object to which plot will be added.
        :param channels:  Optional. Channels that are to be plotted.
        :param args, kwargs:  Optional arguments to pass to plotting function

        :return: Plot object. Either holoviews Layout, or matplotlib plot
        """
        # - Filter spikes by time
        if time_limits is None:
            t_start = self.t_start
            t_stop = self.t_stop
        else:
            execption_limits = (
                f"TSEvent `{self.name}`: `time_limits` must be None or tuple "
                + "of length 2."
            )
            try:
                # - Make sure `time_limits` has correct length
                if len(time_limits) != 2 or not isin:
                    raise ValueError(execption_limits)
                else:
                    t_start = self.t_start if time_limits[0] is None else time_limits[0]
                    t_start = self.t_stop if time_limits[1] is None else time_limits[1]
            except TypeError:
                raise TypeError(exception_limits)
        # - Choose matching events
        times, channels = self(t_start, t_stop, channels)

        if target is None:
            # - Get current plotting backend from global settings
            _use_holoviews, _use_matplotlib = get_plotting_backend()

            if _use_holoviews:
                return (
                    hv.Scatter((times, channels), *args, **kwargs)
                    .redim(x="Time", y="Channel")
                    .relabel(self.name)
                )

            elif _use_matplotlib:
                # - Add `self.name` as label only if a label is not already present
                kwargs["label"] = kwargs.get("label", self.name)
                return plt.scatter(times, channels, *args, **kwargs)

            else:
                raise RuntimeError(
                    f"TSEvent: `{self.name}`: No plotting back-end detected."
                )

        else:
            # - Infer current plotting backend from type of `target`
            if isinstance(target, (hv.Curve, hv.Overlay)):
                target *= (
                    hv.Scatter((times, channels), *args, **kwargs)
                    .redim(x="Time", y="Channel")
                    .relabel(self.name)
                )
                return target.relabel(group=self.name)
            elif isinstance(target, mpl.axes.Axes):
                # - Add `self.name` as label only if a label is not already present
                kwargs["label"] = kwargs.get("label", self.name)
                target.scatter(times, channels, *args, **kwargs)
                return target
            else:
                raise TypeError(
                    f"TSEvent: `{self.name}`: Unrecognized type for `target`. "
                    + "It must be matplotlib Axes or holoviews Curve or Overlay."
                )

    ## -- Methods for finding and extracting data

    def clip(
        self,
        t_start: Optional[float] = None,
        t_stop: Optional[float] = None,
        channels: Union[int, ArrayLike, None] = None,
        include_stop: bool = False,
        compress_channels: bool = False,
        inplace: bool = False,
    ) -> TSEventType:
        """
        clip - Return a TSEvent which is restricted to given time limits and only
                 contains events of selected channels. If time limits are provided,
                 t_start and t_stop attributes will correspond to those. If
                 `compress_channels` is true, channels IDs will be mapped to continuous
                 sequence of integers starting from 0 (e.g. [1,3,6]->[0,1,2]). In this
                 case `num_channels` will be set to the largest new channel ID + 1.
                 Otherwise it will keep its original values, which is also the case for
                 all other attributes.
                 If `inplace` is True, modify `self` accordingly.

        :param t_start:       Time from which on events are returned
        :param t_stop:        Time until which events are returned
        :param channels:      Channels of which events are returned
        :param include_stop:  If there are events with time t_stop include them or not
        :param compress_channels:  Map channel IDs to continuous sequence startign from 0.
                                   Set `num_channels` to largest new ID + 1.
        :param inplase:       Specify whether operation should be performed in place (Default: False)
        :return: TSEvent containing events from the requested channels
        """

        if not inplace:
            new_series = self.copy()
        else:
            new_series = self

        # - Extract matching events
        times, channels = new_series(t_start, t_stop, channels, include_stop)

        # - Update new timeseries
        new_series._times = times
        if t_start is not None:
            new_series._t_start = t_start
        if t_stop is not None:
            new_series._t_stop = t_stop
        if compress_channels and channels.size > 0:
            # - Set channel IDs to sequence starting from 0
            unique_channels, channel_indices = np.unique(channels, return_inverse=True)
            num_channels = unique_channels.size
            new_series._channels = np.arange(num_channels)[channel_indices]
            new_series.num_channels = num_channels
        else:
            new_series._channels = channels

        return new_series

    def raster(
        self,
        dt: float,
        t_start: float = None,
        t_stop: float = None,
        num_timesteps: int = None,
        channels: np.ndarray = None,
        add_events: bool = False,
    ) -> np.ndarray:
        """
        raster - Return rasterized time series data, where each data point
                 represents a time step. Events are represented in a boolean
                 matrix, where the first axis corresponds to time, the second
                 axis to the channel.
                 Events that happen between time steps are projected to the
                 preceding one. If two events happen during one time step
                 within a single channel, they are counted as one, unless
                 add_events is True.
        :param dt:      Length of single time step in raster
        :param t_start:  Time where to start raster - Will start at self.t_start if None
        :param t_stop:  Time where to stop raster. This time point is not included anymore.
                        If None, will use all points until (and including) self.t_stop.
                        If num_timesteps is set, t_stop is ignored.
        :param num_timesteps: Can be used to determine number of time steps directly,
                              directly, instead of providing t_stop
        :param channels:      Array-like Channels, from which data is to be used.
        :param add_events:    bool If True, return integer raster containing number of
                              events for each time step and channel

        :return
            event_raster    Boolean matrix with True indicating presence of events
                            for each time step and channel. If add_events == True,
                            the raster consists of integers, indicating the number
                            of events per time step and channel.
                            First axis corresponds to time, second axis to channel.
        """
        # - Filter time and channels
        t_start = self.t_start if t_start is None else t_start
        if channels is None:
            channels = np.arange(self.num_channels)
        if num_timesteps is None:
            series = self.clip(
                t_start=t_start,
                t_stop=t_stop,
                channels=channels,
                compress_channels=False,
            )
            # - Make sure that last point is also included if `duration` is a
            #   multiple of dt. Therefore floor(...) + 1
            num_timesteps = int(np.floor((series.duration) / dt)) + 1
        else:
            t_stop = t_start + num_timesteps * dt
            series = self.clip(
                t_start=t_start,
                t_stop=t_stop,
                channels=channels,
                compress_channels=False,
            )

        # - Raster for storing event data
        raster_type = int if add_events else bool
        event_raster = np.zeros((num_timesteps, channels.size), raster_type)

        # - Handle empty series
        if len(series) == 0:
            return event_raster

        # - Select data according to time base
        event_times = series.times
        event_channels = series.channels

        ## -- Convert input events and samples to boolen or integer raster
        # - Only consider rasters that have non-zero length
        if num_timesteps > 0:
            # Compute indices for times
            time_indices = np.floor((event_times - t_start) / dt).astype(int)
            if add_events:
                # Count events per time step and channel
                for idx_t, idx_ch in zip(time_indices, event_channels):
                    event_raster[idx_t, idx_ch] += 1
            else:
                # - Print a warning if there are multiple spikes in one time step and channel
                if (
                    (
                        np.diff(np.c_[time_indices, event_channels], axis=0)
                        == np.zeros(2)
                    )
                    .all(axis=1)
                    .any(axis=0)
                ):
                    print(
                        f"TSEvent `{self.name}`: There are channels with multiple events"
                        + " per time step. Consider smaller dt or setting add_events True."
                    )
                # Mark spiking indices with True
                event_raster[time_indices, event_channels] = True

        return event_raster

    def xraster(
        self,
        dt: float,
        t_start: Optional[float] = None,
        t_stop: Optional[float] = None,
        num_timesteps: Optional[int] = None,
        channels: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        xraster - Yields a rasterized time series data, where each data point
                 represents a time step. Events are represented in a boolean
                 matrix, where the first axis corresponds to time, the second
                 axis to the channel.
                 Events that happen between time steps are projected to the
                 preceding one. If two events happen during one time step
                 within a single channel, they are counted as one.
        :param dt:      Length of single time step in raster
        :param t_start:  Time where to start raster - Will start at self.t_start if None
        :param t_stop:  Time where to stop raster. This time point is not included anymore.
                        If None, will use all points until (and including) self.t_stop.
                        If num_timesteps is set, t_stop is ignored.
        :param num_timesteps: Can be used to determine number of time steps directly,
                              directly, instead of providing t_stop
        :param channels:      Array-like Channels, from which data is to be used.

        :yields
            vbEventsRaster  Boolean matrix with True indicating event axis corresponds to channel
        """
        event_raster = self.raster(
            dt=dt,
            t_start=t_start,
            t_stop=t_stop,
            num_timesteps=num_timesteps,
            channels=channels,
        )
        yield from event_raster  # Yield one row at a time

    def save(self, path: str):
        """
        save - Save TSEvent as npz file using np.savez
        :param strPath:     str  Path to save file
        """
        np.savez(
            path,
            times=self.times,
            channels=self.channels,
            t_start=self.t_start,
            t_stop=self.t_stop,
            periodic=self.periodic,
            num_channels=self.num_channels,
            name=self.name,
            strType="TSEvent",  # Indicate that the object is TSEvent
        )
        missing_ending = path.split(".")[-1] != "npz"  # np.savez will add ending
        print(
            "TSEvent `{}` has been stored in `{}`.".format(
                self.name, path + missing_ending * ".npz"
            )
        )

    ## -- Methods for combining time series

    def append_c(self, other_series: TSEventType, inplace: bool = False) -> TSEventType:
        """
        append_c - Spatially append another time series to this one, so that the other
                   series' channel IDs are shifted by `self.num_channels`. The event
                   times remain the same.

        :param other_series: TSEvent or list thereof that will be included in `self`.
        :param inplace:      Conduct operation in-place (Default: False; create a copy)
        :return: TSEvent containing current data, with other TS appended spatially
        """

        # - Create a new time series, or modify this time series
        if not inplace:
            appended_series = self.copy()
        else:
            appended_series = self

        # - Ensure we have a list of timeseries to work on
        if not isinstance(other_series, collections.abc.Iterable):
            series_list = [appended_series, other_series]
        else:
            series_list = [appended_series] + list(other_series)

        # - Check series class
        if not all(isinstance(series, TSEvent) for series in series_list):
            raise TypeError(
                f"TSEvent `{self.name}`: Can only append `TSEvent` objects."
            )

        # - Determine t_start and t_stop
        t_start_new = min(series.t_start for series in series_list)
        t_stop_new = max(series.t_stop for series in series_list)

        # - Determine number of channels for each series
        nums_channels = [series.num_channels for series in series_list]
        print(nums_channels)
        # - Shift for each TSEvent's channels
        channel_shifts = np.cumsum([0] + nums_channels[:-1])
        print(channel_shifts)

        # - Stop if no non-empty series is left
        if not series_list:
            return appended_series

        # - Merge all samples
        times_new = np.concatenate([series.times for series in series_list])
        channels_new = np.concatenate(
            [
                series.channels + shift
                for series, shift in zip(series_list, channel_shifts)
            ]
        )
        print(*(series.channels for series in series_list))
        print(channels_new)

        # - Sort on time and merge
        sort_indices = np.argsort(times_new)
        appended_series._times = times_new[sort_indices]
        appended_series._channels = channels_new[sort_indices].astype(int)
        appended_series._t_start = t_start_new
        appended_series._t_stop = t_stop_new
        appended_series._num_channels = int(np.sum(nums_channels))

        return appended_series

    def append_t(
        self,
        other_series: Union[TimeSeries, Iterable[TimeSeries]],
        offset: float = 0,
        remove_duplicates: bool = False,
        inplace: bool = False,
    ) -> TSEventType:
        """
        append_t - Append another time series to this one, in time, so that the other
                   series' `t_start` is shifted to `t_stop+offset` of `self`.

        :param other_series: TSEvent or list thereof that will be tacked on to the end of `self`
        :param offset:       Scalar or iterable with at least the same number of elements as
                             other_series. If scalar, use same value for all timeseries.
                             Shift `t_start` of corresponding series from `self.t_stop` by this value.
        :param remove_duplicates:  Remove duplicate events in resulting timeseries
        :param inplace:      Conduct operation in-place (Default: False; create a copy)
        :return: TSEvent containing current data, with other TS appended in time
        """

        # - Ensure we have a list of timeseries to work on
        if not isinstance(other_series, collections.abc.Iterable):
            other_series = [other_series]
        else:
            other_series = list(other_series)
        # - Same for offsets
        if not isinstance(offset, collections.abc.Iterable):
            offset_list = [offset] * len(other_series)
        else:
            offset_list = list(offset)
            if len(offset_list) != len(other_series):
                warn(
                    f"TSEvent `{self.name}`: Numbers of provided offsets and TSEvent "
                    + "objects do not match. Will ignore excess elements."
                )

        # - Translate offsets so that they correspond to indiviual delays for each series
        # Delay for first appended series:
        delay1 = offset_list[0] + self.t_stop - other_series[0].t_start
        delay_list = [delay1]
        # Add delays for other lists
        for prev_series, curr_series, offset in zip(
            other_series[:-1], other_series[1:], offset_list[1:]
        ):
            # Time at which previous series stops
            stop_previous = delay_list[-1] + prev_series.t_stop
            # Delay for current series
            delay_list.append(stop_previous + offset - curr_series.t_start)
        print(delay_list)
        # - Let self.merge do the rest
        try:
            return self.merge(
                other_series=other_series,
                delay=delay_list,
                remove_duplicates=remove_duplicates,
                inplace=inplace,
            )
        except TypeError:
            # - Provide matching exception
            raise TypeError(
                f"TSEvent `{self.name}`: Can only append `TSEvent` objects."
            )

    def merge(
        self,
        other_series: Union[TimeSeries, Iterable[TimeSeries]],
        delay: Union[float, Iterable[float]] = 0,
        remove_duplicates: bool = False,
        inplace: bool = False,
    ) -> TSEventType:
        """
        merge - Merge another TSEvent into this one so that they may overlap in time
        :param other_series:       TimeSeries (or list of TimeSeries) to merge into this one
        :param delay:             Scalar or iterable with at least the number of elements
                                   as other_series. If scalar, use same value for all
                                   timeseries. Delay corresponding series by this value.
        :param remove_duplicates:  Remove duplicate events in resulting timeseries
        :param inplace:            Specify whether operation should be performed in place (Default: False)
        :return: self with new samples included
        """

        # - Create a new time series, or modify this time series
        if not inplace:
            merged_series = self.copy()
        else:
            merged_series = self

        # - Ensure we have a list of timeseries to work on
        if not isinstance(other_series, collections.abc.Iterable):
            series_list = [merged_series, other_series]
        else:
            series_list = [merged_series] + list(other_series)
        # - Same for offsets
        if not isinstance(delay, collections.abc.Iterable):
            delay_list = [0] + [delay] * (len(series_list) - 1)
        else:
            delay_list = [0] + list(delay)
            if len(delay_list) != len(series_list):
                warn(
                    f"TSEvent `{self.name}`: Numbers of provided offsets and TSEvent "
                    + "objects do not match. Will ignore excess elements."
                )

        # - Check series class
        if not all(isinstance(series, TSEvent) for series in series_list):
            raise TypeError(
                f"TSEvent `{self.name}`: Can only merge with `TSEvent` objects."
            )

        # - Apply delay
        series_list = [
            series.delay(delay) for series, delay in zip(series_list, delay_list)
        ]
        # - Determine number of channels
        merged_series._num_channels = max(series.num_channels for series in series_list)
        # - Determine t_start and t_stop
        t_start_new = min(series.t_start for series in series_list)
        t_stop_new = max(series.t_stop for series in series_list)
        # - Merge all samples
        times_new = np.concatenate([series.times for series in series_list])
        channels_new = np.concatenate([series.channels for series in series_list])

        # - Remove events with same times and channels
        if remove_duplicates:
            times_new, channels_new = np.unique((times_new, channels_new), axis=1)

        # - Sort on time and merge
        sort_indices = np.argsort(times_new)
        merged_series._times = times_new[sort_indices]
        merged_series._channels = channels_new[sort_indices].astype(int)
        merged_series._t_start = t_start_new
        merged_series._t_stop = t_stop_new

        return merged_series

    ## -- Internal methods

    def _matching_channels(
        self, channels: Union[int, ArrayLike, None] = None
    ) -> np.ndarray:
        """
        _matching_channels - Return boolean array of which events match channel selection
        :param channels:  Channels of which events are to be indicated True
        :return: (times, channels) containing events form the requested channels
        """

        if channels is None:
            channels = np.arange(self.num_channels)
        else:
            # - Check `channels` for validity
            if not (np.min(channels) >= 0 and np.max(channels) < self.num_channels):
                raise IndexError(
                    f"TSEvent `{self.name}`: `channels` must be between 0 and {self.num_channels}."
                )
        # - Make sure elements in `channels` are unique for better performance
        channels = np.unique(channels)

        # - Boolean array of which events match selected channels
        include_events = np.isin(self._channels, channels)

        return include_events

    ## -- Magic methods

    def __call__(
        self,
        t_start: Optional[float] = None,
        t_stop: Optional[float] = None,
        channels: Union[int, ArrayLike, None] = None,
        include_stop: bool = False,
    ) -> (np.ndarray, np.ndarray):
        """
        ts(t_start, t_stop) - Return events in interval between indicated times

        :param t_start:     Time from which on events are returned
        :param t_stop:      Time until which events are returned
        :param channels:  Channels of which events are returned
        :param include_stop:  If there are events with time t_stop include them or not
        :return:
            np.ndarray  Times of events
            np.ndarray  Channels of events
        """
        # - Handle empty TSEvent
        if self.isempty():
            return np.array([]), np.array([], int)

        if t_start is None:
            t_start: float = self.t_start
        if t_stop is None:
            t_stop: float = self.t_stop
            include_stop = True
        # - Permit unsorted bounds
        if t_stop < t_start:
            t_start, t_stop = t_stop, t_start
        # - Events with matching channels
        channel_matches = self._matching_channels(channels)

        if self.periodic:
            # - Repeat events sufficiently often
            all_times = _extend_periodic_times(t_start, t_stop, self)
            num_reps = int(np.round(all_times.size / self.channels.size))
            all_channels = np.tile(self.channels, num_reps)
        else:
            all_times = self.times
            all_channels = self.channels

        if include_stop:
            choose_events_stop: np.ndarray = all_times <= t_stop
        else:
            choose_events_stop: np.ndarray = all_times < t_stop

        choose_events: np.ndarray = (
            (all_times >= t_start) & (choose_events_stop) & channel_matches
        )
        return all_times[choose_events], all_channels[choose_events]

    def __getitem__(self, ind: Union[ArrayLike, slice, int]) -> TSEventType:
        """
        ts[tTime1, tTime2, ...] - Index the events of `self` by with the argument
                                  and return TSEvent with corresponding events.
                                  Other attributes, including `num_channels` and `duration`
                                  are the same as in `self`.
        :return:
            np.array of indexed event times
            np.array of indexed event channels
        """
        indexed_times: np.ndarray = np.atleast_1d(self.times[ind])
        indexed_channels: np.ndarray = np.atleast_1d(self.channels[ind])
        # - New TSEvent with the selected events
        new_series = self.copy()
        new_series._times = indexed_times
        new_series._channels = indexed_channels
        return new_series

    def __repr__(self):
        """
        __repr__() - Return a string representation of this object
        :return: str String description
        """
        if self.isempty():
            return "Empty `TSEvent` object `{}` from t={} to t={}.".format(
                self.name, self.t_start, self.t_stop
            )
        else:
            return "{}periodic `TSEvent` object `{}` from t={} to {}. Channels: {}. Events: {}".format(
                int(not self.periodic) * "non-",
                self.name,
                self.t_start,
                self.t_stop,
                self.num_channels,
                self.times.size,
            )

    def __len__(self):
        return self._times.size

    ## -- Properties

    @property
    def channels(self):
        return self._channels

    @channels.setter
    def channels(self, vnNewChannels):
        # - Check size of new data
        assert np.size(vnNewChannels) == 1 or np.size(vnNewChannels) == np.size(
            self.times
        ), "`vnNewChannels` must be the same size as `times`."

        # - Handle scalar channel
        if np.size(vnNewChannels) == 1:
            vnNewChannels = np.repeat(vnNewChannels, np.size(self._times))

        # - Assign channels
        self._channels = vnNewChannels

    @property
    def num_channels(self):
        return self._num_channels

    @num_channels.setter
    def num_channels(self, nNewNumChannels):
        nMinNumChannels = np.amax(self.channels)
        if nNewNumChannels < nMinNumChannels:
            raise ValueError(
                f"TSContinuous `{self.name}`: `num_channels` must be at least {nMinNumChannels}."
            )
        else:
            self._num_channels = nNewNumChannels


def load_ts_from_file(
    strPath: str, strExpectedType: Optional[str] = None
) -> TimeSeries:
    """
    load_ts_from_file - Load a timeseries object from an npz file.
    :param strPath:     str Filepath to load file
    :param strExpectedType:   str  Specify expected type of timeseires (TSContinuous or TSEvent)
    :return:
        Loaded time series object
    """
    # - Load npz file from specified path
    dLoaded = np.load(strPath)
    # - Check for expected type
    strLoadedType = dLoaded["strType"].item()
    if strExpectedType is not None:
        if not strLoadedType == strExpectedType:
            raise TypeError(
                "Timeseries at `{}` is of type `{}`, which does not match expected type `{}`.".format(
                    strPath, strLoadedType, strExpectedType
                )
            )
    if strLoadedType == "TSContinuous":
        return TSContinuous(
            times=dLoaded["times"],
            samples=dLoaded["samples"],
            t_start=dLoaded["t_start"].item(),
            t_stop=dLoaded["t_stop"].item(),
            interp_kind=dLoaded["interp_kind"].item(),
            periodic=dLoaded["periodic"].item(),
            name=dLoaded["name"].item(),
        )
    elif strLoadedType == "TSEvent":
        return TSEvent(
            times=dLoaded["times"],
            channels=dLoaded["channels"],
            t_start=dLoaded["t_start"].item(),
            t_stop=dLoaded["t_stop"].item(),
            periodic=dLoaded["periodic"].item(),
            num_channels=dLoaded["num_channels"].item(),
            name=dLoaded["name"].item(),
        )
    else:
        raise TypeError("Type `{}` not supported.".format(strLoadedType))
