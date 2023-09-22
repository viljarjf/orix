# -*- coding: utf-8 -*-
# Copyright 2018-2023 the orix developers
#
# This file is part of orix.
#
# orix is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# orix is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with orix.  If not, see <http://www.gnu.org/licenses/>.

"""Base class for 3d objects.

.. note::

    Contents of this module are not meant to be used directly.
"""

from __future__ import annotations

from typing import Optional, Union, TypeVar, Iterable

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["DimensionError", "Object3d"]


# TODO: Replace with typing.Self after python >=3.11, as per PEP 673
Self = TypeVar("Self", bound="Object3d")


class DimensionError(Exception):
    """Error raised when an array passed to a class constructor has an
    incompatible shape.

    Parameters
    ----------
    this
        An orix class with attributes ``dim`` and ``shape``.
    data
        Array.
    """

    def __init__(self, this: Object3d, data: np.ndarray):
        super().__init__(
            f"{this.__class__.__name__} requires data of dimension {this.dim} but "
            f"received dimension {data.shape[-1]}"
        )


class Object3d:
    """Base class for 3d objects.

    .. note::

        This class is not meant to be used directly.

    Parameters
    ----------
    data
        Object data.
    """

    dim: int = None
    """Return the number of dimensions for this object."""  # pragma: no cover

    _data: np.ndarray = None

    __array_ufunc__ = None

    def __init__(self, data: Union[Self, ArrayLike, None] = None) -> None:
        if isinstance(data, Object3d):
            self._data = data.data
        else:
            data = np.atleast_2d(data)
            if data.shape[-1] != self.dim:
                raise DimensionError(self, data)
            self._data = data
        self.__finalize__(data)

    def __finalize__(self, data):
        pass

    @property
    def data(self) -> np.ndarray:
        """Return the object data."""
        return self._data[..., : self.dim]

    @data.setter
    def data(self, data: np.ndarray):
        """Set the object data."""
        self._data[..., : self.dim] = data

    def __repr__(self) -> str:
        """Return a string representation of the data."""
        name = self.__class__.__name__
        shape = str(self.shape)
        data = np.array_str(self.data, precision=4, suppress_small=True)
        return "\n".join([name + " " + shape, data])

    def __getitem__(self: Self, key) -> Self:
        """Return a slice of the object."""
        data = np.atleast_2d(self.data[key])
        obj = self.__class__(data)
        return obj

    def __setitem__(self, key, value: np.ndarray):
        """Set a slice of the data."""
        self.data[key] = value.data

    @classmethod
    def empty(cls: type[Self]) -> Self:
        """Return an empty object with the appropriate dimensions."""
        return cls(np.zeros((0, cls.dim)))

    @property
    def shape(self) -> tuple:
        """Return the shape of the object."""
        return self.data.shape[:-1]

    @property
    def ndim(self) -> int:
        """Return the number of navigation dimensions of the instance.

        For example, if :attr:`data` has shape (4, 5, 6), :attr:`ndim`
        is 3.
        """
        return len(self.shape)

    @property
    def size(self) -> int:
        """Return the total number of entries in this object."""
        return int(np.prod(self.shape))

    @classmethod
    def stack(cls: type[Self], sequence: Iterable[Self]) -> Self:
        """Return a stacked object from the sequence.

        Parameters
        ----------
        sequence
            A sequence of instances of a class inheriting from
            ``Object3d`` to stack.
        """
        sequence = [s._data for s in sequence]
        stack = np.stack(sequence, axis=-2)
        obj = cls(stack[..., : cls.dim])
        obj._data = stack
        return obj

    def flatten(self: Self) -> Self:
        """Return a new object with the same data in a single column."""
        obj = self.__class__(self.data.T.reshape(self.dim, -1).T)
        real_dim = self._data.shape[-1]
        obj._data = self._data.T.reshape(real_dim, -1).T
        return obj

    def unique(
        self: Self, return_index: bool = False, return_inverse: bool = False
    ) -> Union[
        tuple[Self, np.ndarray, np.ndarray],
        tuple[Self, np.ndarray],
        Self,
    ]:
        """Return a new object containing only this object's unique
        entries.

        Unless overridden, this method returns the numerically unique
        entries. Also removes zero entries which are assumed to be
        degenerate.

        Parameters
        ----------
        return_index
            If ``True``, will also return the indices of the (flattened)
            data where the unique entries were found.
        return_inverse
            If ``True``, will also return the indices to reconstruct the
            (flattened) data from the unique data.

        Returns
        -------
        dat
            The numerically unique entries.
        idx
            The indices of the unique data in the (flattened) array if
            ``return_index=True``.
        inv
            The indices of the (flattened) data in the unique array if
            ``return_inverse=True``.
        """
        data = self.flatten()._data.round(10)
        data = data[~np.all(np.isclose(data, 0), axis=1)]  # Remove zeros
        _, idx, inv = np.unique(data, axis=0, return_index=True, return_inverse=True)
        obj = self.__class__(data[np.sort(idx), : self.dim])
        obj._data = data[np.sort(idx)]
        if return_index and return_inverse:
            return obj, idx, inv
        elif return_index and not return_inverse:
            return obj, idx
        elif return_inverse and not return_index:
            return obj, inv
        else:
            return obj

    @property
    def norm(self) -> np.ndarray:
        """Return the norm of the data."""
        return np.sqrt(np.sum(np.square(self.data), axis=-1))

    @property
    def unit(self: Self) -> Self:
        """Return the unit object."""
        with np.errstate(divide="ignore", invalid="ignore"):
            obj = self.__class__(np.nan_to_num(self.data / self.norm[..., np.newaxis]))
            return obj

    def squeeze(self: Self) -> Self:
        """Return a new object with length one dimensions removed.

        Returns
        -------
        obj
            New object with no 1-dimensions.
        """
        obj = self.__class__(self)
        obj._data = np.atleast_2d(np.squeeze(self._data))
        return obj

    def reshape(self: Self, *shape: int) -> Self:
        """Return a new object containing the same data with a new
        shape.

        Parameters
        ----------
        shape
            New shape of object.

        Returns
        -------
        obj
            New object with new shape.
        """
        obj = self.__class__(self.data.reshape(*shape, self.dim))
        obj._data = self._data.reshape(*shape, -1)
        return obj

    def transpose(self: Self, *axes: Optional[int]) -> Self:
        """Return a new object containing the same data transposed.

        If :attr:`ndim` is originally 2, then order may be undefined. In
        this case the first two dimensions will be transposed.

        Parameters
        ----------
        axes
            The transposed axes order. Only navigation axes need to be
            defined. May be undefined if self only contains two
            navigation dimensions.

        Returns
        -------
        obj
            The object transposed.
        """
        # 1d object should not be transposed
        if len(self.shape) == 1:
            return self

        # allow 2d object to be transposed without specifying axes
        if not len(axes):
            if len(self.shape) != 2:
                raise ValueError("Axes must be defined for more than two dimensions.")
            else:
                # swap first two axes
                axes = (1, 0)

        if len(axes) != len(self.shape):
            raise ValueError(
                "Number of axes is ill-defined: "
                + f"{tuple(axes)} does not fit with {self.shape}."
            )

        return self.__class__(self.data.transpose(*axes + (-1,)))

    def get_random_sample(
        self: Self, size: Optional[int] = 1, replace: bool = False, shuffle: bool = False
    ) -> Self:
        """Return a random sample of a given size in a flattened
        instance.

        Parameters
        ----------
        size
            Number of samples to draw. Cannot be greater than the size
            of this instance. If not given, a single sample is drawn.
        replace
            See :meth:`numpy.random.Generator.choice`.
        shuffle
            See :meth:`numpy.random.Generator.choice`.

        Returns
        -------
        new
            New, flattened instance of a given size with elements drawn
            randomly from this instance.

        See Also
        --------
        numpy.random.Generator.choice
        """
        n = self.size
        if size > n:
            raise ValueError(f"Cannot draw a sample greater than {self.size}")
        rng = np.random.default_rng()
        sample = rng.choice(n, size=size, replace=replace, shuffle=shuffle)
        sample = np.unravel_index(sample, shape=self.shape)
        return self[sample]
