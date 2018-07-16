import numpy as np
import warnings
from scipy import signal
from collections import UserList
from functools import reduce


class CNNWeight(UserList):
    def __init__(self, inShape=None, nKernels=1, kernel_size=(5, 5), mode='same'):
        '''
        CNNWeight class is virtual array that allows convolutions on the input through indexing
        :param inShape:     tuple Shape of input
        :param nKernels:    int No. of kernels for this convolutial weight matrix
        :param kernel_size: tuple Shape of each kernel
        :param mode:        str 'same' or 'valid' or 'full'
        (For more information on convolution parameters look into scipy.convolve2d documentation

        Important Note: inShape needs to be set before the use of indexing on this object.
        If left undefine/None, the input dimension is inferred from input dimensions, if the data is binary.
        If it is an integer index, then an IndexError is raised
        '''
        self.nKernels = nKernels
        self.kernel_size = kernel_size
        self.ndim = 2  # Because the input and output is always flattened
        self.data = None  # Initialized when inShape is assigned
        self._inShape = None
        self.inShape = inShape
        self.mode = mode
        self.img_data_format = 'channels_last'

    def __len__(self):
        return len(self.data)

    def __contains__(self, x):
        return self.data.__contains__(x)

    def __repr__(self):
        return str(self.data)

    def __getitem__(self, index):
        # NOTE: This approach is optimal when there is dense spiking activity.
        # If this is used on a per spike basis, the simulations will be pretty
        # slow. So this will need some optimization
        img_data_format = self.img_data_format  # Local variable
        data = self.data    # Local variable
        try:
            if (type(index) is int) or (type(index) is list):
                # indexed by integer
                bIndex = np.zeros(self.inShape).astype(bool).flatten()
                bIndex[index] = True
                return self.__getitem__(bIndex)
            elif index.dtype is np.dtype(int):
                bIndex = np.zeros(self.inShape).astype(bool).flatten()
                bIndex[index] = True
                return self.__getitem__(bIndex)
            elif index.dtype is np.dtype('bool'):
                # Meat of this fuction
                # Reshape input
                bIndex = index
                bIndexReshaped = bIndex.reshape(self.inShape)
                if self.inShape is None:
                    self.inShape == bIndexReshaped.shape

                # The actual convolution happens here
                aConvolution = []
                # Convolve each kernel individually
                for nKernelIndex in range(self.nKernels):
                    if img_data_format == 'channels_last':
                        kernel = data[..., nKernelIndex]
                    fmConvolution = None  # Reset value
                    if bIndexReshaped.ndim == 3:
                        if img_data_format == 'channels_last':
                            nFeatureMaps = bIndexReshaped.shape[-1]
                        # Convolve each feature of input individually
                        for nFeatureIndex in range(nFeatureMaps):
                            img = bIndexReshaped[..., nFeatureIndex]
                            kern = kernel[..., nFeatureIndex]
                            fmConvolutionFeature = self._do_convolve_2d(img, kern)
                            if fmConvolution is None:
                                fmConvolution = fmConvolutionFeature
                            else:
                                fmConvolution += fmConvolutionFeature
                    else:
                        fmConvolution = self._do_convolve_2d(bIndexReshaped, kernel)
                    aConvolution.append(fmConvolution)

                fmConvolution = np.array(aConvolution)
                fmConvolution = np.moveaxis(fmConvolution, 0, -1)
                return fmConvolution.flatten()
            else:
                raise TypeError('Indices should be of type [bool]')
        except AttributeError as e:
            raise e
        except IndexError as e:
            raise e

    def _do_convolve_2d(self, bIndexReshaped, kernel):
        '''
        Performs the actual convolution call of a 2D image with a 2D kernel
        '''
        # This is the function to modify for stride, padding and other parameters
        # NOTE: This function should also defines what the shape of the output is going to be
        return signal.convolve2d(bIndexReshaped, kernel, mode=self.mode, boundary='fill')

    def __setitem__(self, index, value):
        '''
        Set weights
        '''
        raise Exception('Not Implemented')

    @property
    def shape(self):
        outSize = int(reduce(lambda x, y: x*y, self.outShape))*self.nKernels
        inSize = int(reduce(lambda x, y: x*y, self.inShape))
        return (inSize, outSize)

    @property
    def size(self):
        outSize = int(reduce(lambda x, y: x*y, self.outShape))*self.nKernels
        inSize = int(reduce(lambda x, y: x*y, self.inShape))
        return (inSize*outSize)

    @property
    def outShape(self):
        if self._outShape is None:
            self._outShape = self._do_convolve_2d(np.zeros(self.inShape[:2]), np.zeros(self.kernel_size)).shape
        return self._outShape

    @property
    def inShape(self):
        return self._inShape

    @inShape.setter
    def inShape(self, inShape):
        '''
        Set the variable inShape and initialize a corresponding kernel
        '''
        if inShape is None:
            inShape = []
        if inShape == self._inShape:
            return  # No change
        self._inShape = inShape
        self._outShape = None
        self.initialize_weights()

    def initialize_weights(self):
        '''
        This function reinitializes the weights of this object
        '''
        # Initialize kernels
        if self.data is not None:
            warnings.warn('Re-Initializing convolutional kernel because of inSize change')
        self.data = np.random.rand(*self.kernel_size, *self._inShape[2:], self.nKernels)    # Kernel
