"""
Dynap-SE graph graph mapper package

- Create a graph using the :py:meth:`~.graph.GraphModule.as_graph` API
- Call :py:func:`.mapper`

Note : Existing modules are reconstructed considering consistency with Xylo support.


Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com

15/09/2022
"""
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple, Union

from copy import deepcopy
import numpy as np
from dataclasses import dataclass

from rockpool.graph import GraphModuleBase
from rockpool.devices.dynapse.default import dlayout

__all__ = ["mapper", "DRCError", "DRCWarning"]


class DRCError(ValueError):
    pass


class DRCWarning(Warning, DRCError):
    pass


@dataclass
class DFA_Placement:
    """
    DFA_Placement defines an algorithmic state machine and keeps track of weight installation process

    :Parameters:

    :param lif: the bit that identifies lif layer can be processed at that step, defaults to False (linear state)
    :type lif: bool
    :param rec: the bit that identifies recurrent layer can be processed at that step, defaults to False (linear state)
    :type rec: bool
    :param linear: the bit that identifies linear layer can be processed at that step, defaults to True (linear state)
    :type linear: bool
    """

    lif: bool = False
    rec: bool = False
    linear: bool = True

    def __eq__(self, __o: DFA_Placement) -> bool:
        """
        __eq__ overrides the equality operator

        :param __o: the object to be compared
        :type __o: DFA_Placement
        :return: True if all data fields are equal
        :rtype: bool
        """
        return self.lif == __o.lif and self.rec == __o.rec and self.linear == __o.linear

    def assign(self, __o: DFA_Placement) -> None:
        """
        assign equates an existing object and the class instance of interest

        :param __o: the external object
        :type __o: DFA_Placement
        """
        self.lif = __o.lif
        self.rec = __o.rec
        self.linear = __o.linear

    def next(self, flag_rec: Optional[bool] = None):
        """
        next handles the state transition depending on the current step and the inputs

        :param flag_rec: the recurrent layer flag, it branches the post-lift state, defaults to None
        :type flag_rec: Optional[bool], optional
        :raises ValueError: post-lif state requires recurrent flag input!
        :raises ValueError: Illegal State!
        """

        if self == self.state_linear():
            self.__pre_lif()

        elif self == self.state_pre_lif():
            self.__post_lif()

        elif self == self.state_post_lif():
            if flag_rec is None:
                raise ValueError("post-lif state requires recurrent flag input!")
            if flag_rec:
                self.__linear()
            else:
                self.__pre_lif()
        else:
            raise ValueError("Illegal State!")

    ### --- Hidden assignment methods --- ###
    def __pre_lif(self) -> None:
        self.assign(self.state_pre_lif())

    def __post_lif(self) -> None:
        self.assign(self.state_post_lif())

    def __linear(self) -> None:
        self.assign(self.state_linear())

    #### --- Define all the possible states --- ###
    @classmethod
    def state_pre_lif(cls) -> DFA_Placement:
        return DFA_Placement(lif=True, rec=False, linear=False)

    @classmethod
    def state_post_lif(cls) -> DFA_Placement:
        return DFA_Placement(lif=False, rec=True, linear=True)

    @classmethod
    def state_linear(cls) -> DFA_Placement:
        return DFA_Placement(lif=False, rec=False, linear=True)


@dataclass
class NPGrid:
    """
    Addresses a subset of the numpy array that is to be used for reading or writing
    Implements error checking methods

    :Parameters:

    :param row: a two dimensional row slice
    :type row: Tuple[int]
    :param col: a two dimensional column slice
    :type col: Tuple[int]
    """

    row: Tuple[int]
    col: Tuple[int]

    def __post_init__(self):
        """
        __post_init__ checks the row and col limit validity after initialization

        :raises ValueError: row limits (min,max) represented wrong!
        :raises ValueError: col limits (min,max) represented wrong!
        :raises ValueError: row lower end be smaller than 0!
        :raises ValueError: col lower end cannot be smaller than 0!
        :raises ValueError: row indices should be in the non-decreasing order!
        :raises ValueError: col indices should be in the non-decreasing order!
        """
        if len(self.row) > 2:
            raise ValueError("row limits (min,max) represented wrong!")

        if len(self.col) > 2:
            raise ValueError("col limits (min,max) represented wrong!")

        if self.row[0] < 0:
            raise ValueError("row lower end be smaller than 0!")

        if self.col[0] < 0:
            raise ValueError("col lower end cannot be smaller than 0!")

        if self.row[1] < self.row[0]:
            raise ValueError("row indices should be in the non-decreasing order!")

        if self.col[1] < self.col[0]:
            raise ValueError("col indices should be in the non-decreasing order!")

    def place(
        self, destination: np.ndarray, source: np.ndarray, in_place: bool = True
    ) -> np.ndarray:
        """
        place places the smaller array to a bigger array given the grid constraints

        :param destination: the bigger destination array
        :type destination: np.ndarray
        :param source: the smaller source array
        :type source: np.ndarray
        :param in_place: change the destination object in place or deep copy, defaults to True
        :type in_place: bool, optional
        :raises ValueError: row indice is beyond the limits of the destination matrix!
        :raises ValueError: col indice is beyond the limits of the destination matrix!
        :raises ValueError: Source array shape is different then mask position!
        :return: modified destination array
        :rtype: np.ndarray
        """
        diff = lambda tup: abs(tup[0] - tup[1])

        if self.row[1] > destination.shape[0]:
            raise ValueError(
                "row indice is beyond the limits of the destination matrix!"
            )
        if self.col[1] > destination.shape[1]:
            raise ValueError(
                "col indice is beyond the limits of the destination matrix!"
            )

        if (diff(self.row), diff(self.col)) != source.shape:
            raise ValueError("Source array shape is different then mask position!")

        if in_place:
            destination[self.row[0] : self.row[1], self.col[0] : self.col[1]] = source
            return destination

        else:
            dest = deepcopy(destination)
            dest[self.row[0] : self.row[1], self.col[0] : self.col[1]] = source
            return dest


def mapper(
    graph: GraphModuleBase,
) -> Dict[str, float]:
    """
    mapper mapps a computational graph onto Dynap-SE2 architecture

    returns a specification object which can be used to create a config object

    :param graph: _description_
    :type graph: GraphModuleBase
    :return: _description_
    :rtype: Dict[str, float]
    """

    w_in = None
    w_rec = None

    Idc = None
    If_nmda = None
    Igain_ahp = None
    Igain_ampa = None
    Igain_gaba = None
    Igain_nmda = None
    Igain_shunt = None
    Igain_mem = None
    Ipulse_ahp = None
    Ipulse = None
    Iref = None
    Ispkthr = None
    Itau_ahp = None
    Itau_ampa = None
    Itau_gaba = None
    Itau_nmda = None
    Itau_shunt = None
    Itau_mem = None
    Iw_ahp = None
    Iw_base = None

    return {
        "mapped_graph": graph,
        "weights_in": w_in,
        "weights_rec": w_rec,
        "Idc": Idc,
        "If_nmda": If_nmda,
        "Igain_ahp": Igain_ahp,
        "Igain_ampa": Igain_ampa,
        "Igain_gaba": Igain_gaba,
        "Igain_nmda": Igain_nmda,
        "Igain_shunt": Igain_shunt,
        "Igain_mem": Igain_mem,
        "Ipulse_ahp": Ipulse_ahp,
        "Ipulse": Ipulse,
        "Iref": Iref,
        "Ispkthr": Ispkthr,
        "Itau_ahp": Itau_ahp,
        "Itau_ampa": Itau_ampa,
        "Itau_gaba": Itau_gaba,
        "Itau_nmda": Itau_nmda,
        "Itau_shunt": Itau_shunt,
        "Itau_mem": Itau_mem,
        "Iw_ahp": Iw_ahp,
        "Iw_base": Iw_base,
    }
