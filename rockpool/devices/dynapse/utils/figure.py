"""
Dynap-SE1 visualisation aid utility functions

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
01/10/2021
"""
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from rockpool.timeseries import TSEvent, TSContinuous

from rockpool.devices.dynapse.utils.spike_input import custom_spike_train
from rockpool.devices.dynapse.definitions import ArrayLike, NeuronKey
from rockpool.devices.dynapse.infrastructure.router import Router

import matplotlib
import matplotlib.pyplot as plt


class Figure:
    """
    Figure is a utility class which gathers the DynapSim specific plotting methods together
    """

    syn_map = {
        "AMPA": 0,
        "GABA": 1,
        "NMDA": 2,
        "SHUNT": 3,
    }

    @staticmethod
    def __select_input_channels(
        input_ts: TSEvent,
        weighted_mask: Optional[ArrayLike] = None,
        virtual: bool = True,
        idx_map: Optional[Dict[str, Dict[int, NeuronKey]]] = None,
        title: Optional[str] = None,
    ) -> Tuple[TSEvent, List[str]]:

        """
        __select_input_channels helper function to select and label channels from a TSEvent object.
        Given a weighted mask and input ts, it creates a new TSEvent object with selected channels
        and label them in accordance with given index map.

        :param input_ts: TSEvent object to be processed and clipped
        :type input_ts: TSEvent
        :param weighted_mask: A channel mask with non-binary values
        :type weighted_mask: np.ndarray
        :param virtual: Indicates if the pre-synaptic neruon is spike-generator(virtual) or real in-device neuron, defaults to True
        :type virtual: bool, optional
        :param idx_map: a dictionary of the mapping between matrix indexes of the neurons and their global unique neuron keys, defaults to None
        :type idx_map: Optional[Dict[int, NeuronKey]], optional
        :param title: The name of the resulting input spike train, defaults to None
        :type title: Optional[str], optional
        :raises ValueError: Weighted mask should include as many elements as number of channels in the input_ts!
        :return: spikes_ts, labels
            :spikes_ts: selected spike trains
            :labels: list of string labels generated for the channels in the following format : `<NeuronType>[<NeuronID>]<Repetition>`
                :NeuronType: can be 's' or 'n'. 's' means spike generator and 'n' means real in-device neuron
                :NeuronID: can be NeuronKey indicating chipID, coreID and neuronID of the neuron, can be universal neruon ID or matrix index.
                :Repetition: represents the number of synapse indicated in the weighted mask
                    n[(3, 0, 20)]x3 -> real neuron in chip 3, core 0, with neuronID 20, with weight mask 3
                    s[0]x1 -> virtual neuron(spike generator), with weight mask 1
        :rtype: Tuple[TSEvent, List[str]]
        """
        if weighted_mask is None:
            weighted_mask = np.ones(input_ts.num_channels)

        if not isinstance(weighted_mask, np.ndarray):
            weighted_mask = np.array(weighted_mask)

        if len(weighted_mask) != input_ts.num_channels:
            raise ValueError(
                "Weighted mask should include as many elements as number of channels in the input_ts!"
            )

        # Temporary storage lists
        spikes = []
        labels = []

        # Create an empty TSEvent object to append channels
        spikes_ts = custom_spike_train(
            times=np.array([]), channels=None, duration=input_ts.duration, name=title
        )

        # Select the channels of the TSEvent object with a weighted mask
        nonzero_idx = np.argwhere(weighted_mask).flatten()
        if nonzero_idx.size:
            input_st = input_ts.clip(channels=nonzero_idx, remap_channels=True)
            spikes.append(input_st)

            # Spike generator or in-device neuron
            n = "s" if virtual else "n"

            # Map weight matric indices to NeuronKey
            if idx_map is not None:
                name = list(map(lambda idx: f"{n}{[idx_map[idx]]}", nonzero_idx))

            else:
                name = list(map(lambda idx: f"{n}[{idx}]", nonzero_idx))

            count = list(map(lambda c: f"{c}", weighted_mask[nonzero_idx]))
            # labels.extend(list(map(lambda t: f"{t[0]}x{t[1]}", zip(name, count))))
            labels.extend(list(map(lambda t: f"{t[0]}", zip(name, count))))

        # Merge spike trains in one TSEvent object
        for ts in spikes:
            spikes_ts = spikes_ts.append_c(ts)

        return spikes_ts, labels

    @staticmethod
    def __spike_input_post(
        input_ts: TSEvent,
        output_ts: TSEvent,
        post: Union[NeuronKey, int],
        syn_name: str,
        router: Router,
        *args,
        **kwargs,
    ) -> Tuple[TSEvent, List[str]]:
        """
        __spike_input_post gather together all the input spikes of a post-synaptic neuron.
        The post-synaptic neuron can be provided as matrix index in the absence of a index map.
        If an index map is provided, the post-neuron id should be compatible with map. That is,
        if neurons are represented in `NeuronKey` format(chipID, coreID, neuronID), the post-synaptic neuron should be indicated in
        `NeuronKey` format as well. One can provide a pre-synaptic neuron or
        a pre-synaptic neuron list to constrain the incoming connections to be listed. In this case,
        the pre-synaptic neurons should also obey the same format in the `idx_map`.

        :param input_ts: Input spike trains fed to DynapSEFPGA or DynapSim object
        :type input_ts: TSEvent
        :param output_ts: Output spike trains of DynapSim object
        :type output_ts: TSEvent
        :param post: matrix index(if idx_map absent) or NeuronKey(if idx_map provided) of the post synaptic neuron defined inside the `mod`
        :type post: Union[NeuronKey, int]
        :param syn_name: the listening synapse type of post-synaptic neuron of interest (e.g. "AMPA", "GABA", ...)
        :type syn_name: str
        :param router: the router object storing the index map and weight masks
        :type router: Router
        :raises IndexError: "NeuronKey {post} is not defined in the index map!
        return: spikes_ts, labels
            :spikes_ts: input spike trains to post-synaptic neuron
            :labels: list of string labels generated for the channels in the following format : `<NeuronType>[<NeuronID>]<Repetition>`
                :NeuronType: can be 's' or 'n'. 's' means spike generator and 'n' means real in-device neuron
                :NeuronID: can be NeuronKey indicating chipID, coreID and neuronID of the neuron, can be universal neruon ID or matrix index.
                :Repetition: represents the number of synapse indicated in the weighted mask
                    n[(3, 0, 20)]x3 -> real neuron in chip 3, core 0, with neuronID 20, connection repeated 3 times (idx_map provided)
                    s[0]x1 -> virtual neuron(spike generator), connection repeated once
        :rtype: Tuple[TSEvent, List[str]]
        """

        syn_idx = Figure.syn_map[syn_name]

        if isinstance(post, tuple):
            reverse_map = {v: k for k, v in router.idx_map.items()}
            post_idx = reverse_map[post]
        else:
            post_idx = post

        # Gather external spike trains sending to post-synaptic neuron of interest
        if router.w_in_mask is not None:
            mask_in = router.w_in_mask[:, post_idx, syn_idx]
            ext_ts, ext_labels = Figure.__select_input_channels(
                input_ts, mask_in, True, router.tag_map_in, *args, **kwargs
            )
        else:
            ext_ts = custom_spike_train(np.array([]), None, input_ts.duration)
            ext_labels = []

        # Gather recurrent input spike trains sending to post-synaptic neuron of interest
        mask = router.w_rec_mask[:, post_idx, syn_idx]
        rec_ts, rec_labels = Figure.__select_input_channels(
            output_ts, mask, False, router.idx_map, *args, **kwargs
        )

        # Merge external and recurrent inputs
        spikes_ts = ext_ts.append_c(rec_ts)
        labels = ext_labels + rec_labels

        return spikes_ts, labels

    @staticmethod
    def plot_spikes_label(
        spikes_ts: TSEvent,
        labels: Optional[List[str]] = None,
        idx_map: Optional[Dict[int, NeuronKey]] = None,
        ax: Optional[matplotlib.axes.Axes] = None,
        cmap: Optional[str] = "rainbow",
        ylabel: Optional[str] = None,
        *args,
        **kwargs,
    ) -> matplotlib.collections.PathCollection:
        """
        plot_spikes_label helper function used for plotting the spike train with labeled channels

        :param spikes_ts: spike train to be plotted
        :type spikes_ts: TSEvent
        :param labels: Channel labels, defaults to None
        :type labels: Optional[List[str]], optional
        :param idx_map: dictionary to map the matrix indexes of the neurons to a NeuronKey to be used in the label, defaults to None
        :type idx_map: Optional[Dict[int, NeuronKey]]], optional
        :param ax: The sub-plot axis to plot the figure, defaults to None
        :type ax: Optional[matplotlib.axes.Axes], optional
        :param cmap: matplotlib color map. For full list, please check https://matplotlib.org/stable/tutorials/colors/colormaps.html, defaults to "rainbow"
        :type cmap: Optional[str], optional
        :param ylabel: y axis label to set, defaults to None
        :type ylabel: Optional[str], optional
        :raises ValueError: `labels` should include as many elements as number of channels in the `spikes_ts`
        :return: `PathCollection` object returned by scatter plot
        :rtype: matplotlib.collections.PathCollection
        """
        if labels is None:
            labels = list(map(str, range(spikes_ts.num_channels)))

        if idx_map is not None:
            labels = [idx_map[__channel] for __channel in np.unique(spikes_ts.channels)]

        if len(labels) > spikes_ts.num_channels:
            raise ValueError(
                "`labels` should include as many elements as number of channels in the `spikes_ts`"
            )

        if ax is not None:
            plt.sca(ax)

        # Empty figure if no incoming spikes
        if spikes_ts:
            scatter = spikes_ts.plot(c=spikes_ts.channels, cmap=cmap, *args, **kwargs)
            plt.yticks(range(len(labels)), labels)

        else:
            scatter = spikes_ts.plot()

        if ylabel is not None:
            plt.ylabel(ylabel)

        plt.tight_layout()

        return scatter

    @staticmethod
    def plot_Ix(
        Ix_record: np.ndarray,
        Ithr: Optional[Union[float, np.ndarray]] = None,
        dt: float = 1e-3,
        name: Optional[str] = None,
        idx_map: Optional[Dict[int, NeuronKey]] = None,
        margin: Optional[float] = 0.2,
        ax: Optional[matplotlib.axes.Axes] = None,
        line_ratio: float = 0.3,
        ylabel: str = "Current (A)",
        *args,
        **kwargs,
    ) -> TSContinuous:
        """
        plot_Ix converts an `Ix_record` current measurements/recordings obtained from the record dictionary to a `TSContinuous` object and plot

        :param Ix_record: Membrane or synapse currents of the neurons recorded with respect to time (T,N)
        :type Ix_record: np.ndarray
        :param Ithr: Spike threshold or any other upper threshold for neurons. Both a single float number for global spike threshold and an array of numbers for neuron-specific thresholds can be provided. Plotted with dashed lines if provided, defaults to None
        :type Ithr: Optional[float], optional
        :param dt: The discrete time resolution of the recording, defaults to 1e-3
        :type dt: float, optional
        :param name: title of the figure, name of the `TSContinuous` object, defaults to None
        :type name: str, optional
        :param idx_map: a dictionary of the mapping between matrix indexes of the neurons and their global unique neuron keys, defaults to None
        :type idx_map: Optional[Dict[int, NeuronKey]], optional
        :param margin: The margin between the edges of the figure and edges of the lines, defaults to 0.2
        :type margin: Optional[float], optional
        :param ax: The sub-plot axis to plot the figure, defaults to None
        :type ax: Optional[matplotlib.axes.Axes], optional
        :param line_ratio: the ratio between Imem lines and the Ispkthr lines, defaults to 0.3
        :type line_ratio: float, optional
        :param ylabel: ylabel value to be printed
        :type ylabel: str, optional
        :return: Imem current in `TSContinuous` object format
        :rtype: TSContinuous
        """
        f_margin = 1.0 + margin if margin is not None else 1.0

        if ax is not None:
            plt.sca(ax)

        # Convert and plot
        Ix = TSContinuous.from_clocked(Ix_record, dt=dt, name=name)
        _lines = Ix.plot(stagger=np.float32(Ix.max * f_margin), *args, **kwargs)
        plt.ylabel(ylabel)

        if idx_map is not None:
            ax = plt.gca()
            handles, labels = ax.get_legend_handles_labels()
            ax.legend(
                handles[::-1],
                [f"n[{n_key}]" for n_key in idx_map.values()][::-1],
                bbox_to_anchor=(1.05, 1.05),
            )

        plt.tight_layout()

        # Upper threshold lines
        if Ithr is not None:
            linewidth = _lines[0]._linewidth * line_ratio
            Ithr = np.ones_like(Ix_record) * Ithr
            Ithr = TSContinuous.from_clocked(Ithr, dt=dt)
            Ithr.plot(
                stagger=np.float32(Ix.max * f_margin),
                linestyle="dashed",
                linewidth=linewidth,
            )

        return Ix

    @staticmethod
    def plot_spikes(
        spikes: np.ndarray,
        dt: float = 1e-3,
        name: Optional[str] = None,
        idx_map: Optional[Dict[int, NeuronKey]] = None,
        virtual: bool = False,
        ax: Optional[matplotlib.axes.Axes] = None,
        *args,
        **kwargs,
    ) -> TSEvent:
        """
        plot_spikes converts a `spikes` record obtained from the record dictionary to a `TSEvent` object and plot

        :param spikes: input or output spikes of the neurons recorded with respect to time (T,N)
        :type spikes: np.ndarray
        :param dt: The discrete time resolution of the recording, defaults to 1e-3
        :type dt: float, optional
        :param name: title of the figure, name of the `TSEvent` object, defaults to None
        :type name: str, optional
        :param idx_map: a dictionary of the mapping between matrix indexes of the neurons and their global unique neuron keys, defaults to None
        :type idx_map: Optional[Dict[int, NeuronKey]], optional
        :param ax: The sub-plot axis to plot the figure, defaults to None
        :type ax: Optional[matplotlib.axes.Axes], optional
        :return: spikes in `TSEvent` object format
        :rtype: TSEvent
        """

        if ax is not None:
            plt.sca(ax)

        # Convert and plot
        spikes_ts = TSEvent.from_raster(spikes, dt=dt, name=name)
        spikes_ts.plot(*args, **kwargs)

        if idx_map is not None:
            plt.ylabel("Channels [ChipID, CoreID, NeuronID]")
            prefix = "s" if virtual else "n"
            plt.yticks(
                list(idx_map.keys()),
                [f"{prefix}[{n_key}]" for n_key in idx_map.values()],
            )
        plt.tight_layout()

        return spikes_ts

    @staticmethod
    def split_yaxis(
        top_ax: matplotlib.axes.Axes,
        bottom_ax: matplotlib.axes.Axes,
        top_bottom_ratio: Tuple[float],
    ) -> None:
        """
        split_yaxis arrange ylimits such that two different plots can share the same y axis without any intersection

        :param top_ax: the axis to place on top
        :type top_ax: matplotlib.axes.Axes
        :param bottom_ax: the axis to place on bottom
        :type bottom_ax: matplotlib.axes.Axes
        :param top_bottom_ratio: the ratio between top and bottom axes
        :type top_bottom_ratio: Tuple[float]
        """

        def arrange_ylim(
            ax: matplotlib.axes.Axes, place_top: bool, factor: float
        ) -> None:
            """
            arrange_ylim helper function to arrange y_limits

            :param ax: the axis to change the limits
            :type ax: matplotlib.axes.Axes
            :param place_top: place the axis of interest to top or bottom
            :type place_top: bool
            :param factor: the factor to multiply the y-range and allocate space to the other plot
            :type factor: float
            """
            bottom, top = ax.get_ylim()

            if place_top:
                bottom = bottom - factor * (top - bottom)
            else:
                top = top + factor * (top - bottom)

            ax.set_ylim(top=top, bottom=bottom)

        f_top = top_bottom_ratio[1] / top_bottom_ratio[0]
        f_bottom = top_bottom_ratio[0] / top_bottom_ratio[1]

        arrange_ylim(top_ax, 1, f_top)
        arrange_ylim(bottom_ax, 0, f_bottom)

    @staticmethod
    def normalize_y(y: float, ax: matplotlib.axes.Axes) -> float:
        """
        normalize normalize a y value with respect to axis limits

        :param y: the value to be normalized
        :type y: float
        :param ax: the axis of interest to get the limits
        :type ax: matplotlib.axes.Axes
        :return: normalized y value (in [0,1] if the value is within the limits)
        :rtype: float
        """

        bottom, top = ax.get_ylim()
        res = (y - bottom) / (top - bottom)
        return res

    @staticmethod
    def normalize_x(x: float, ax: matplotlib.axes.Axes) -> float:
        """
        normalize normalize a x value with respect to axis limits

        :param x: the value to be normalized
        :type x: float
        :param ax: the axis of interest to get the limits
        :type ax: matplotlib.axes.Axes
        :return: normalized x value (in [0,1] if the value is within the limits)
        :rtype: float
        """

        x_min, x_max = ax.get_xlim()
        res = (x - x_min) / (x_max - x_min)
        return res

    @staticmethod
    def plot_Isyn_trace(
        input_ts: TSEvent,
        output_ts: TSEvent,
        record_dict: Dict[str, np.ndarray],
        post: Union[NeuronKey, int],
        syn_name: str,
        router: Router,
        dt: float = 1e-3,
        title: Optional[str] = None,
        ax: Optional[matplotlib.axes.Axes] = None,
        plot_guides: bool = True,
        line_ratio: float = 0.3,
        top_bottom_ratio: Tuple[float] = (2, 1),
        s: float = 10.0,
        save: bool = False,
        path: str = "figure.png",
    ) -> Tuple[TSContinuous, TSEvent, List[str]]:
        """
        plot_Isyn_trace plots a synaptic current(AMPA, GABA, NMDA, SHUNT, or AHP) of a pre-synaptic neuron
        with the input spikes trains affecting the synaptic current. By making `plot_guides` = True,
        guide lines from the spikes to increments on the synaptic current can be drawn.

        :param input_ts: Input spike trains fed to DynapSEFPGA or DynapSim object
        :type input_ts: TSEvent
        :param output_ts: Output spike trains of DynapSim object
        :type output_ts: TSEvent
        :param record_dict: is a dictionary containing the recorded state variables of `mod` during the evolution at each time step
        :type record_dict: Dict[str, np.ndarray]
        :param post: matrix index(if idx_map absent) or NeuronKey(if idx_map provided) of the post synaptic neuron defined inside the `mod`
        :type post: Union[NeuronKey, int]
        :param syn_name: the listening synapse type of post-synaptic neuron of interest (e.g. "AMPA", "GABA_A", ...)
        :type syn_name: str
        :param router: the router object storing the index map and weight masks
        :type router: Router
        :param dt: The discrete time resolution of the recording, defaults to 1e-3
        :type dt: float, optional
        :param title: The title of the resulting plot, name of the `Isyn` object returned, defaults to None
        :type title: Optional[str], optional
        :param ax: The sub-plot axis to plot the figure, defaults to None
        :type ax: Optional[matplotlib.axes.Axes], optional
        :param plot_guies: plot the spikes to Isyn current guide lines(dashed) or not, defaults to True
        :type plot_guies: bool, optional
        :param line_ratio: the ratio between Isyn lines and the spike to Isyn guide lines, defaults to 0.3
        :type line_ratio: float, optional
        :param top_bottom_ratio: the ratio between top and bottom axes, defaults to (1, 2)
        :type top_bottom_ratio: Tuple[float], optional
        :param s: spike dot size, defaults to 10
        :type s: float, optional
        :param save: save the figure or not defaults to False
        :type save: bool, optional
        :param path: the path to save the figure if save is True defaults to "figure.png"
        :type path: str, optional
        :raises IndexError: "NeuronKey {post} is not defined in the index map!
        return: Isyn, spikes_ts, labels
            :Isyn: Isyn current in `TSContinuous` object format
            :spikes_ts: input spike trains to post-synaptic neuron
            :labels: list of string labels generated for the channels in the following format : `<NeuronType>[<NeuronID>]<Repetition>`
                :NeuronType: can be 's' or 'n'. 's' means spike generator and 'n' means real in-device neuron
                :NeuronID: can be NeuronKey indicating chipID, coreID and neuronID of the neuron, can be universal neruon ID or matrix index.
                :Repetition: represents the number of synapse indicated in the weighted mask
                    n[(3, 0, 20)]x3 -> real neuron in chip 3, core 0, with neuronID 20, connection repeated 3 times (idx_map provided)
                    s[0]x1 -> virtual neuron(spike generator), connection repeated once
        :rtype: Tuple[TSContinuous, TSEvent, List[str]]
        """

        if isinstance(post, tuple):
            reverse_map = {v: k for k, v in router.idx_map.items()}
            post_idx = reverse_map[post]
        else:
            post_idx = post

        # Plot the Isyn and spikes on a common x axis and different y axes
        if ax is None:
            _, ax_spike = plt.subplots()
        else:
            ax_spike = ax
            plt.sca(ax_spike)

        ax_syn = ax_spike.twinx()

        # Generate a title
        if title is None:
            title = f"$I_{{{syn_name}}}$ n[{post}]"

        # Plot input spikes
        # AHP handler
        if syn_name != "AHP":
            spikes_ts, labels = Figure.__spike_input_post(
                input_ts,
                output_ts,
                post,
                syn_name,
                router,
                title="",
            )
        else:
            weighted_mask = np.zeros(output_ts.num_channels)
            weighted_mask[post_idx] = 1

            spikes_ts, labels = Figure.__select_input_channels(
                output_ts,
                weighted_mask,
                virtual=False,
                idx_map=router.idx_map,
                title="",
            )

        scatter = Figure.plot_spikes_label(spikes_ts, labels, ax=ax_spike, s=s)

        # Plot the synaptic current and the incoming spikes
        Isyn = Figure.plot_Ix(
            record_dict[f"i{syn_name.lower()}"][:, post_idx],
            dt=dt,
            name=title,
            ax=ax_syn,
        )

        # Arrange the y limits so that plots won't intersect
        Figure.split_yaxis(ax_syn, ax_spike, top_bottom_ratio)

        # Plot guides to trace the effect of a spike on the synaptic current
        if plot_guides:

            # x,y info is in the scatter object
            for x, y in scatter.get_offsets():
                y_syn = Isyn.samples[int(x // dt)][0]
                linewidth = ax_syn.lines[0]._linewidth * line_ratio

                # dashed lines, color can be obtained from the scatter object
                plt.axvline(
                    x,
                    ymin=Figure.normalize_y(y, ax_spike),
                    ymax=Figure.normalize_y(y_syn, ax_syn),
                    linestyle="dashed",
                    linewidth=linewidth,
                    color=scatter.to_rgba(y),
                )

        plt.tight_layout()

        if save:
            plt.savefig(path, transparent=True, bbox_inches="tight", pad_inches=0)

        return Isyn, spikes_ts, labels
