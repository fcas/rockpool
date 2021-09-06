"""
Bias Generator module for Dynap-SE devices used in coarse-fine values to bias current generation

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
02/09/2021
"""

import numpy as np

from typing import (
    Tuple,
)


class BiasGen:
    """
    BiasGen is a static class encapsulating coarse and fine value to bias current and linear bias value conversion utilities.

    :Attributes:

    :attr coarse_base: base currents depending on given coarse index
    :type coarse_base: np.ndarray
    :attr scaling_factor: scaling factor to convert bias currents to linear bias values
    :type scaling_factor: np.float32
    :attr fine_range: the maximum value for a fine value to get
    :type fine_range: np.uint8
    """

    coarse_base = np.array(
        [
            1.5e-11,  # I0
            1.05e-10,  # I1
            8.2e-10,  # I2
            6.5e-09,  # I3
            5e-08,  # I4
            4e-07,  # I5
            3.2e-06,  # I6
            2.4e-05,  # I7
        ],
        dtype=np.float32,
    )

    scaling_factor = np.float32(1e14)
    fine_range = np.uint8(255)

    @staticmethod
    def get_bias(coarse: np.uint8, fine: np.uint8) -> np.float64:
        """
        coarse_fine_2_linear
        The very large scale integration(VLSI) neurons on DYNAP-SE are controlled by configurable current
        sources called “biases”. For each bias, there is an integer coarse value :math:`C \\in [0,7]` and
        an integer fine value :math:`F \\in [0,255]`, which together determine the amplitude of the current

        :param coarse: integer coarse value :math:`C \\in [0,7]`
        :type coarse: np.uint8
        :param fine: integer fine value :math:`F \\in [0,255]`
        :type fine: np.uint8
        """
        max_current = BiasGen.coarse_base[coarse]
        base_current = np.divide(max_current, BiasGen.fine_range, dtype=np.float64)
        bias = np.multiply(fine, base_current, dtype=np.float64)
        return bias

    @staticmethod
    def get_linear(coarse: np.uint8, fine: np.uint8) -> np.float32:
        bias = BiasGen.get_bias(coarse, fine)
        linear = np.multiply(bias, BiasGen.scaling_factor, dtype=np.float32)
        linear = np.round(linear, 0)
        return linear

    @staticmethod
    def get_coarse_fine(
        linear: np.float32, coarse_smallest: bool = True, exact: bool = True
    ) -> Tuple[np.uint8, np.uint8]:
        """
        get_coarse_fine gives a coarse/fine tuple given a linear bias value

        :param linear: the linear bias value
        :type linear: np.float32
        :param coarse_smallest: Choose the smallest coarse value possible. In this case, fine value would be slightly higher. If False, the function returns the biggest possible coarse value. defaults to False
        :type coarse_smallest: bool, optional
        :param exact: If true, the function returns a corse fine tuple in the case that the exact linear value can be obtained using the ``BiasGen.get_linear()`` function else the function returns None. If false, the function returns the closest possible coarse and fine tuple, defaults to True
        :type exact: bool, optional
        :return: coarse and fine value tuple
        :rtype: Tuple[np.uint8, np.uint8]
        """

        # If linear bias value is 0, no need to calculate!
        if linear == 0:
            return np.uint8(0), np.uint8(0)

        if coarse_smallest:
            couple_idx = 0

        else:  # coarse_biggest
            couple_idx = -1

        def propose_coarse_candidates() -> np.ndarray:
            """
            propose_coarse_candidates gives coarse base currents which can possibly create the linear value desired.
            Multiple coarse base current might generate the same current given a proper fine value!

            :return: an array of coarse value candidate tuples
            :rtype: np.ndarray
            """

            max_linear = np.multiply(BiasGen.coarse_base, BiasGen.scaling_factor)
            min_linear = np.divide(max_linear, BiasGen.fine_range + 1, dtype=np.float32)

            upper_bound = max_linear >= linear
            lower_bound = min_linear <= linear
            condition = np.logical_and(upper_bound, lower_bound)

            candidates = np.where(condition)[0]
            return candidates.astype(np.uint8)

        def propose_coarse_fine_tuple(coarse: np.uint8) -> Tuple[np.uint8, np.uint8]:
            """
            propose_coarse_fine_tuple finds a fine value which creates the linear bias(exactly or very close to!) desired given the coarse value.

            :param coarse: the coarse index value
            :type coarse: np.uint8
            :return: candidate coarse fine tuple
            :rtype: Tuple[np.uint8, np.uint8]
            """

            fine = np.divide(
                linear * BiasGen.fine_range,
                BiasGen.coarse_base[coarse] * BiasGen.scaling_factor,
                dtype=np.float32,
            )
            fine = np.uint8(np.round(fine))
            return coarse, fine

        ## -- Coarse Fine Search -- ##

        candidates = propose_coarse_candidates()
        couples = []

        for coarse in candidates:
            coarse, fine = propose_coarse_fine_tuple(coarse)

            if exact:  # Exact linear value should be obtained via the coarse fine tuple
                if linear == BiasGen.get_linear(coarse, fine):
                    couples.append((coarse, fine))
                else:
                    continue
            else:
                couples.append((coarse, fine))

        if couples:
            return couples[couple_idx]
        else:
            return None

    @staticmethod
    def get_lookup_table() -> np.ndarray:
        """
        get_lookup_table provides a lookup table with always increasing linear biases.
        Please note that due to the floating point precision issues, the linear bias values are not
        the same as the C++ samna implementation. However the variation is small. In comparison:
            Mismatched elements: 296 / 5436 (5.45%)
            Max absolute difference: 256.
            Max relative difference: 5.16192974e-06

        The original lookup table can be downloaded from:
            https://gitlab.com/neuroinf/ctxctl_contrib/-/blob/samna-dynapse1-NI-demo/linear_fine_coarse_bias_map.npy

        :return: an array of [coarse, fine, linear bias]
        :rtype: np.ndarray
        """
        lookup = []
        for c in range(len(BiasGen.coarse_base)):
            for f in range(BiasGen.fine_range + 1):
                linear = BiasGen.get_linear(c, f)
                if lookup:
                    if linear > lookup[-1][2] * 1.00001:
                        lookup.append([c, f, linear])
                else:
                    lookup.append([c, f, linear])

        lookup = np.array(lookup, dtype=np.float32)
        return lookup