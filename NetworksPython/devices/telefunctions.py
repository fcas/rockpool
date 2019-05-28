# ----
# telefunctions.py - Functions that are to be teleported if RPyC is used
# Author: Felix Bauer, aiCTX AG, felix.bauer@ai-ctx.com
# ----

import copy
import os
from typing import Optional, Union, List, Tuple

from .params import FPGA_ISI_LIMIT, NUM_NEURONS_CORE, NUM_CORES_CHIP, NUM_CHIPS
from . import remotefunctions

# - Names of all functions to be teleported
__all__ = [
    "extract_event_data",
    "generate_fpga_event_list",
    "_generate_buffered_filter",
    "load_biases",
    "save_biases",
    "copy_biases",
    "get_all_neurons",
    "clear_chips",
    "_reset_connections",
    "remove_all_connections_to",
    "set_connections",
    "_define_silence_neurons",
    "_define_reset_silencing",
]


def extract_event_data(events) -> (tuple, tuple):
    """
    extract_event_data - Extract timestamps and neuron IDs from list of recorded events.
    :param events:     list  SpikeEvent objects from BufferedEventFilter
    :return:
        lTimeStamps     list  Timestamps of events
        neuron_ids      list  Neuron IDs of events
    """
    # Extract event timestamps and neuron IDs. Skip events with neuron None.
    event_tuples: List[Tuple] = [
        (event.timestamp, event.neuron.get_id())
        for event in events
        if isinstance(event.neuron, ctxdynapse.DynapseNeuron)
    ]
    try:
        timestamps, neuron_ids = zip(*event_tuples)
    except ValueError as e:
        # - Handle emptly event lists
        if len(event_tuples) == 0:
            timestamps = ()
            neuron_ids = ()
        else:
            raise e
    return timestamps, neuron_ids


def generate_fpga_event_list(
    discrete_isi_list: list,
    neuron_ids: list,
    targetcore_mask: int,
    targetchip_id: int,
    fpga_isi_limit: int = FPGA_ISI_LIMIT,
    correct_isi: bool = True,
) -> list:
    """
    generate_fpga_event_list - Generate a list of FpgaSpikeEvent objects
    :param discrete_isi_list:  array-like  Inter-spike intervalls in Fpga time base
    :param neuron_ids:     array-like  IDs of neurons corresponding to events
    :param neuron_id:       int ID of source neuron
    :param targetcore_mask: int Coremask to determine target cores
    :fpga_isi_limit:         int Maximum ISI size (in time steps)
    :correct_isi:           bool Correct too large ISIs in discrete_isi_list

    :return:
        event  list of generated FpgaSpikeEvent objects.
    """

    # - Make sure objects live on required side of RPyC connection
    targetcore_mask = int(targetcore_mask)
    targetchip_id = int(targetchip_id)
    neuron_ids = copy.copy(neuron_ids)
    discrete_isi_list = copy.copy(discrete_isi_list)

    if correct_isi:
        discrete_isi_list, neuron_ids = remotefunctions._auto_insert_dummies(
            discrete_isi_list, neuron_ids, fpga_isi_limit
        )

    def generate_fpga_event(neuron_id: int, isi: int) -> "ctxdynapse.FpgaSpikeEvent":
        """
        generate_fpga_event - Generate a single FpgaSpikeEvent objects.
        :param neuron_id:       int ID of source neuron
        :param isi:            int Timesteps after previous event before
                                    this event will be sent
        :return:
            event  ctxdynapse.FpgaSpikeEvent
        """
        event = ctxdynapse.FpgaSpikeEvent()
        event.target_chip = targetchip_id
        event.core_mask = 0 if neuron_id is None else targetcore_mask
        event.neuron_id = 0 if neuron_id is None else neuron_id
        event.isi = isi
        return event

    # - Generate events
    print("dynapse_control: Generating event list")
    events = [
        generate_fpga_event(neuron_id, isi)
        for neuron_id, isi in zip(neuron_ids, discrete_isi_list)
    ]
    return events


def _generate_buffered_filter(model: "ctxdynapse.Model", record_neuron_ids: list):
    """
    _generate_buffered_filter - Generate and return a BufferedEventFilter object that
                               records from neurons specified in record_neuron_ids.
    :param model:               ctxdynapse model
    :param record_neuron_ids:    list  IDs of neurons to be recorded.
    """
    return ctxdynapse.BufferedEventFilter(model, record_neuron_ids)


def load_biases(filename: str, core_ids: Optional[Union[list, int]] = None):
    """
    load_biases - Load biases from python file under path filename
    :param filename:  str  Path to file where biases are stored.
    :param core_ids:    list, int or None  IDs of cores for which biases
                                            should be loaded. Load all if
                                            None.
    """

    def use_line(codeline: str):
        """
        use_line - Determine whether codeline should be executed considering
                   the IDs of cores in core_ids
        :param codeline:  str  Line of code to be analyzed.
        :return:  bool  Whether line should be executed or not.
        """
        try:
            core_id = int(codeline.split("get_bias_groups()[")[1][0])
        except IndexError:
            # - Line is not specific to core ID
            return True
        else:
            # - Return true if addressed core is in core_ids
            return core_id in core_ids

    if core_ids is None:
        core_ids = list(range(NUM_CHIPS * NUM_CORES_CHIP))
        load_all_cores = True
    else:
        # - Handle integer arguments
        if isinstance(core_ids, int):
            core_ids = [core_ids]
        load_all_cores = False

    with open(os.path.abspath(filename)) as file:
        # list of lines of code of the file. Skip import statement.
        codeline_list = file.readlines()[1:]
        # Iterate over lines of file to apply biases
        for command in codeline_list:
            if load_all_cores or use_line(command):
                exec(command)

    print(
        "dynapse_control: Biases have been loaded from {}.".format(
            os.path.abspath(filename)
        )
    )


def save_biases(filename: str, core_ids: Optional[Union[list, int]] = None):
    """
    save_biases - Save biases in python file under path filename
    :param filename:  str  Path to file where biases should be saved.
    :param core_ids:    list, int or None  ID(s) of cores whose biases
                                            should be saved. If None,
                                            save all cores.
    """

    if core_ids is None:
        core_ids = list(range(NUM_CHIPS * NUM_CORES_CHIP))
    else:
        # - Handle integer arguments
        if isinstance(core_ids, int):
            core_ids = [core_ids]
        # - Include cores in filename, consider possible file endings
        filename_parts: List[str] = filename.split(".")
        # Information to be inserted in filename
        insertstring = "_cores_" + "_".join(str(core_id) for core_id in core_ids)
        try:
            filename_parts[-2] += insertstring
        except IndexError:
            # filename does not contain file ending
            filename_parts[0] += insertstring
            filename_parts.append("py")
        filename = ".".join(filename_parts)

    biasgroup_list = ctxdynapse.model.get_bias_groups()
    # - Only save specified cores
    biasgroup_list = [biasgroup_list[i] for i in core_ids]
    with open(filename, "w") as file:
        file.write("import ctxdynapse\n")
        file.write("save_file_model_ = ctxdynapse.model\n")
        for core_id, bias_group in zip(core_ids, biasgroup_list):
            biases = bias_group.get_biases()
            for bias in biases:
                file.write(
                    'save_file_model_.get_bias_groups()[{0}].set_bias("{1}", {2}, {3})\n'.format(
                        core_id,
                        bias.get_bias_name(),
                        bias.get_fine_value(),
                        bias.get_coarse_value(),
                    )
                )
    print(
        "dynapse_control: Biases have been saved under {}.".format(
            os.path.abspath(filename)
        )
    )


def copy_biases(sourcecore_id: int = 0, targetcore_ids: Optional[List[int]] = None):
    """
    copy_biases - Copy biases from one core to one or more other cores.
    :param sourcecore_id:   int  ID of core from which biases are copied
    :param targetcore_ids: int or array-like ID(s) of core(s) to which biases are copied
                            If None, will copy to all other neurons
    """

    targetcore_ids = copy.copy(targetcore_ids)
    if targetcore_ids is None:
        # - Copy biases to all other cores except the source core
        targetcore_ids = list(range(16))
        targetcore_ids.remove(sourcecore_id)
    elif isinstance(targetcore_ids, int):
        targetcore_ids = [targetcore_ids]

    # - List of bias groups from all cores
    biasgroup_list = ctxdynapse.model.get_bias_groups()
    sourcebiases = biasgroup_list[sourcecore_id].get_biases()

    # - Set biases for target cores
    for tgtcore_id in targetcore_ids:
        for bias in sourcebiases:
            biasgroup_list[tgtcore_id].set_bias(
                bias.bias_name, bias.fine_value, bias.coarse_value
            )

    print(
        "dynapse_control: Biases have been copied from core {} to core(s) {}".format(
            sourcecore_id, targetcore_ids
        )
    )


def get_all_neurons(
    model: "ctxdynapse.Model", virtual_model: "ctxdynapse.VirtualModel"
) -> (List, List, List):
    """
    get_all_neurons - Get hardware, virtual and shadow state neurons
                      from model and virtual_model and return them
                      in arrays.
    :param model:  ctxdynapse.Model
    :param virtual_model: ctxdynapse.VirtualModel
    :return:
        List  Hardware neurons
        List  Virtual neurons
        List  Shadow state neurons
    """
    hw_neurons: List = model.get_neurons()
    virtual_neurons: List = virtual_model.get_neurons()
    shadow_neurons: List = model.get_shadow_state_neurons()
    print("dynapse_control: Fetched all neurons from models.")
    return hw_neurons, virtual_neurons, shadow_neurons


def clear_chips(chip_ids: Optional[list] = None):
    """
    clear_chips - Clear the physical CAM and SRAM cells of the chips defined
                  in chip_ids.
                  This is necessary when CtxControl is loaded (and only then)
                  to make sure that the configuration of the model neurons
                  matches the hardware.

    :param chip_ids:   list  IDs of chips to be cleared.
    """

    # - Make sure chip_ids is a list
    if chip_ids is None:
        return

    if isinstance(chip_ids, int):
        chip_ids = [chip_ids]

    # - Make sure that chip_ids is on correct side of RPyC connection
    chip_ids = copy.copy(chip_ids)

    for nchip in chip_ids:
        print("dynapse_control: Clearing chip {}.".format(nchip))

        # - Clear CAMs
        ctxdynapse.dynapse.clear_cam(int(nchip))
        print("\t CAMs cleared.")

        # - Clear SRAMs
        ctxdynapse.dynapse.clear_sram(int(nchip))
        print("\t SRAMs cleared.")

    # - Update list of initialized chips
    global initialized_chips
    for nchip in chip_ids:
        # Mark chips as initialized
        if nchip not in initialized_chips:
            initialized_chips.append(nchip)
    # Sort list of initialized chips
    initialized_chips = sorted(initialized_chips)
    # - Update list of initialized neurons
    global initialized_neurons
    initialized_neurons = [
        neuron_id
        for nchip in initialized_chips
        for neuron_id in range(NUM_NEURONS_CHIP * nchip, NUM_NEURONS_CHIP * (nchip + 1))
    ]

    print("dynapse_control: {} chip(s) cleared.".format(len(chip_ids)))


def _reset_connections(core_ids: Optional[list] = None, apply_diff=True):
    """
    _reset_connections - Reset connections going to all nerons of cores defined
                         in core_ids. Core IDs from 0 to 15.
    :param core_ids:   list  IDs of cores to be reset
    :param apply_diff:  bool  Apply changes to hardware. Setting False is useful
                              if new connections will be set afterwards.
    """
    # - Make sure core_ids is a list
    if core_ids is None:
        return

    if isinstance(core_ids, int):
        core_ids = [core_ids]

    # - Make sure that core_ids is on correct side of RPyC connection
    core_ids = copy.copy(core_ids)

    # - Get shadow state neurons
    shadow_neurons = ctxdynapse.model.get_shadow_state_neurons()

    for core_id in core_ids:
        print("dynapse_control: Clearing connections of core {}.".format(core_id))

        # - Reset neuron weights in model
        for neuron in shadow_neurons[
            core_id * NUM_NEURONS_CORE : (core_id + 1) * NUM_NEURONS_CORE
        ]:
            # - Reset SRAMs for this neuron
            srams = neuron.get_srams()
            for sram_idx in range(1, 4):
                srams[sram_idx].set_target_chip_id(0)
                srams[sram_idx].set_virtual_core_id(0)
                srams[sram_idx].set_used(False)
                srams[sram_idx].set_core_mask(0)

            # - Reset CAMs for this neuron
            for cam in neuron.get_cams():
                cam.set_pre_neuron_id(0)
                cam.set_pre_neuron_core_id(0)
        print("\t Model neuron weights have been reset.")
    print("dynapse_control: {} core(s) cleared.".format(len(core_ids)))

    if apply_diff:
        # - Apply changes to the connections on chip
        ctxdynapse.model.apply_diff_state()
        print("dynapse_control: New state has been applied to the hardware")


def remove_all_connections_to(
    neuron_ids: List, model: "ctxdynapse.Model", apply_diff: bool = True
):
    """
    remove_all_connections_to - Remove all presynaptic connections
                                to neurons defined in neuron_ids
    :param neuron_ids:      list  IDs of neurons whose presynaptic
                                      connections should be removed
    :param model:          ctxdynapse.model
    :param apply_diff:      bool If False do not apply the changes to
                                 chip but only to shadow states of the
                                 neurons. Useful if new connections are
                                 going to be added to the given neurons.
    """
    # - Make sure that neuron_ids is on correct side of RPyC connection
    neuron_ids = copy.copy(neuron_ids)

    # - Get shadow state neurons
    shadow_neurons = ctxdynapse.model.get_shadow_state_neurons()

    # - Reset neuron weights in model
    for neuron in shadow_neurons:
        # - Reset SRAMs
        srams = neuron.get_srams()
        for sram_idx in range(1, 4):
            srams[sram_idx].set_target_chip_id(0)
            srams[sram_idx].set_virtual_core_id(0)
            srams[sram_idx].set_used(False)
            srams[sram_idx].set_core_mask(0)

        # - Reset CAMs
        for cam in neuron.get_cams():
            cam.set_pre_neuron_id(0)
            cam.set_pre_neuron_core_id(0)

    print("dynapse_control: Shadow state neuron weights have been reset")

    if apply_diff:
        # - Apply changes to the connections on chip
        model.apply_diff_state()
        print("dynapse_control: New state has been applied to the hardware")


def set_connections(
    preneuron_ids: list,
    postneuron_ids: list,
    syntypes: list,
    shadow_neurons: list,
    virtual_neurons: Optional[list],
    connector: "nnconnector.DynapseConnector",
):
    """
    set_connections - Set connections between pre- and post synaptic neurons from lists.
    :param preneuron_ids:       list  N Presynaptic neurons
    :param postneuron_ids:      list  N Postsynaptic neurons
    :param syntypes:       list  N or 1 Synapse type(s)
    :param shadow_neurons:      list  Shadow neurons that the indices correspond to.
    :param virtual_neurons:     list  If None, presynaptic neurons are shadow neurons,
                                      otherwise virtual neurons from this list.
    :param connector:   nnconnector.DynapseConnector
    """
    preneuron_ids = copy.copy(preneuron_ids)
    postneuron_ids = copy.copy(postneuron_ids)
    syntypes = copy.copy(syntypes)
    presyn_neuron_population: List = shadow_neurons if virtual_neurons is None else virtual_neurons

    # - Neurons to be connected
    presyn_neurons = [presyn_neuron_population[i] for i in preneuron_ids]
    postsyn_neurons = [shadow_neurons[i] for i in preneuron_ids]

    # - Logical IDs of pre adn post neurons
    logical_pre_ids = [neuron.get_id() for neuron in presyn_neurons]
    logical_post_ids = [neuron.get_id() for neuron in postsyn_neurons]
    # - Make sure that neurons are on initialized chips
    if virtual_neurons is None and not set(logical_pre_ids).issubset(
        initialized_neurons
    ):
        raise ValueError(
            "dynapse_control: Some of the presynaptic neurons are on chips that have not"
            + " been cleared since starting cortexcontrol. This may result in unexpected"
            + " behavior. Clear those chips first."
        )
    if not set(logical_post_ids).issubset(initialized_neurons):
        raise ValueError(
            "dynapse_control: Some of the postsynaptic neurons are on chips that have not"
            + " been cleared since starting cortexcontrol. This may result in unexpected"
            + " behavior. Clear those chips first."
        )

    # - Set connections
    connector.add_connection_from_list(presyn_neurons, postsyn_neurons, syntypes)

    print("dynapse_control: {} connections have been set.".format(len(preneuron_ids)))


# def _define_silence_neurons():
#     @local_arguments
#     def silence_neurons(neuron_ids):
#         """
#         silence_neurons - Assign time contant tau2 to neurons definedin neuron_ids
#                           to make them silent.
#         :param neuron_ids:  list  IDs of neurons to be silenced
#         """
#         if isinstance(neuron_ids, int):
#             neuron_ids = (neuron_ids,)
#         neurons_per_chip = NUM_CORES_CHIP * NUM_NEURONS_CORE
#         for id_neur in neuron_ids:
#             ctxdynapse.dynapse.set_tau_2(
#                 id_neur // neurons_per_chip,  # Chip ID
#                 id_neur % neurons_per_chip,  # Neuron ID on chip
#             )
#         print("dynapse_control: Set {} neurons to tau 2.".format(len(neuron_ids)))

#     return silence_neurons


# def _define_reset_silencing():
#     @local_arguments
#     def reset_silencing(core_ids):
#         """
#         reset_silencing - Assign time constant tau1 to all neurons on cores defined
#                           in core_ids. Convenience function that does the same as
#                           global _reset_silencing but also updates self._is_silenced.
#         :param core_ids:   list  IDs of cores to be reset
#         """
#         if isinstance(core_ids, int):
#             core_ids = (core_ids,)
#         for id_neur in core_ids:
#             ctxdynapse.dynapse.reset_tau_1(
#                 id_neur // NUM_CORES_CHIP,  # Chip ID
#                 id_neur % NUM_CORES_CHIP,  # Core ID on chip
#             )
#         print("dynapse_control: Set neurons of cores {} to tau 1.".format(core_ids))

#     return reset_silencing