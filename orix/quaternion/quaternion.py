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

from __future__ import annotations

from typing import Optional, Tuple, Union
import warnings

import dask.array as da
from dask.diagnostics import ProgressBar
import numpy as np
import quaternion
from scipy.spatial.transform import Rotation as SciPyRotation

from orix._util import deprecated, deprecated_argument
from orix.base import Object3d
from orix.quaternion import _conversions
from orix.vector import AxAngle, Homochoric, Miller, Rodrigues, Vector3d

# Used to round values below 1e-16 to zero
_FLOAT_EPS = np.finfo(float).eps


class Quaternion(Object3d):
    r"""Basic quaternion object.

    Quaternions support the following mathematical operations:
        - Unary negation.
        - Inversion.
        - Multiplication with other quaternions and vectors.

    Quaternion-quaternion multiplication for two quaternions
    :math:`q_1 = (a_1, b_1, c_1, d_1)`
    and :math:`q_2 = (a_2, b_2, c_2, d_2)`
    with :math:`q_3 = (a_3, b_3, c_3, d_3) = q_1 \cdot q_2` follows as:

    .. math::
       a_3 = a_1 \cdot a_2 - b_1 \cdot b_2 - c_1 \cdot c_2 - d_1 \cdot d_2

       b_3 = a_1 \cdot b_2 + b_1 \cdot a_2 + c_1 \cdot d_2 - d_1 \cdot c_2

       c_3 = a_1 \cdot c_2 - b_1 \cdot d_2 + c_1 \cdot a_2 + d_1 \cdot b_2

       d_3 = a_1 \cdot d_2 + b_1 \cdot c_2 - c_1 \cdot b_2 + d_1 \cdot a_2

    Quaternion-vector multiplication with a three-dimensional vector
    :math:`v = (x, y, z)` calculates a rotated vector
    :math:`v' = q \cdot v \cdot q^{-1}` and follows as:

    .. math::
       v'_x = x(a^2 + b^2 - c^2 - d^2) + 2(z(a \cdot c + b \cdot d) + y(b \cdot c - a \cdot d))

       v'_y = y(a^2 - b^2 + c^2 - d^2) + 2(x(a \cdot d + b \cdot c) + z(c \cdot d - a \cdot b))

       v'_z = z(a^2 - b^2 - c^2 + d^2) + 2(y(a \cdot b + c \cdot d) + x(b \cdot d - a \cdot c))
    """

    # --------------------------- Properties ------------------------- #

    dim = 4

    @property
    def a(self) -> np.ndarray:
        """Return or set the scalar quaternion component.

        Parameters
        ----------
        value : numpy.ndarray
            Scalar quaternion component.
        """
        return self.data[..., 0]

    @a.setter
    def a(self, value: np.ndarray):
        """Set the scalar quaternion component."""
        self.data[..., 0] = value

    @property
    def b(self) -> np.ndarray:
        """Return or set the first vector quaternion component.

        Parameters
        ----------
        value : numpy.ndarray
            First vector quaternion component.
        """
        return self.data[..., 1]

    @b.setter
    def b(self, value: np.ndarray):
        """Set the first vector quaternion component."""
        self.data[..., 1] = value

    @property
    def c(self) -> np.ndarray:
        """Return or set the second vector quaternion component.

        Parameters
        ----------
        value : numpy.ndarray
            Second vector quaternion component.
        """
        return self.data[..., 2]

    @c.setter
    def c(self, value: np.ndarray):
        """Set the second vector quaternion component."""
        self.data[..., 2] = value

    @property
    def d(self) -> np.ndarray:
        """Return or set the third vector quaternion component.

        Parameters
        ----------
        value : numpy.ndarray
            Third vector quaternion component.
        """
        return self.data[..., 3]

    @d.setter
    def d(self, value: np.ndarray):
        """Set the third vector quaternion component."""
        self.data[..., 3] = value

    @property
    def axis(self) -> Vector3d:
        """Return the axis of rotation."""
        axis = Vector3d(np.stack((self.b, self.c, self.d), axis=-1))
        a_is_zero = self.a < -1e-6
        axis[a_is_zero] = -axis[a_is_zero]
        norm_is_zero = axis.norm == 0
        axis[norm_is_zero] = Vector3d.zvector() * np.sign(self.a[norm_is_zero].data)
        axis.data /= axis.norm[..., np.newaxis]
        return axis

    @property
    def angle(self) -> np.ndarray:
        """Return the angle of rotation."""
        return 2 * np.nan_to_num(np.arccos(np.abs(self.a)))

    @property
    def antipodal(self) -> Quaternion:
        """Return the quaternion and its antipodal."""
        return self.__class__(np.stack([self.data, -self.data]))

    @property
    def conj(self) -> Quaternion:
        r"""Return the conjugate of the quaternion
        :math:`q^* = a - bi - cj - dk`.
        """
        q = quaternion.from_float_array(self.data).conj()
        return Quaternion(quaternion.as_float_array(q))

    # ----------------------- Dunder functions ---------------------- #

    def __invert__(self) -> Quaternion:
        return self.__class__(self.conj.data / (self.norm**2)[..., np.newaxis])

    def __mul__(self, other: Union[Quaternion, Vector3d]):
        if isinstance(other, Quaternion):
            q1 = quaternion.from_float_array(self.data)
            q2 = quaternion.from_float_array(other.data)
            return other.__class__(quaternion.as_float_array(q1 * q2))
        elif isinstance(other, Vector3d):
            # check broadcast shape is correct before calculation, as
            # quaternion.rotat_vectors will perform outer product
            # this keeps current __mul__ broadcast behaviour
            q1 = quaternion.from_float_array(self.data)
            v = quaternion.as_vector_part(
                (q1 * quaternion.from_vector_part(other.data)) * ~q1
            )
            if isinstance(other, Miller):
                m = other.__class__(xyz=v, phase=other.phase)
                m.coordinate_format = other.coordinate_format
                return m
            else:
                return other.__class__(v)
        return NotImplemented

    def __neg__(self) -> Quaternion:
        return self.__class__(-self.data)

    # -------------------- from_*() class methods -------------------- #

    # TODO: Remove before 0.13.0
    @classmethod
    @deprecated(since="0.12", removal="0.13", alternative="from_axes_angles")
    def from_neo_euler(cls, neo_euler: "NeoEuler") -> Quaternion:
        """Create unit quaternion(s) from a neo-euler (vector)
        representation.

        Parameters
        ----------
        rf
            Rodrigues-Frank vector parametrization of quaternion(s).

        ignore_warnings = False
            Silences warnings related to large errors or large vectors

        Returns
        -------
        q
            Unit quaternion(s).

        Notes
        -------
        Rodrigues vectors are often useful as a visualization tool. However,
        the length scales with :math:\tan(\theta/2), as does their relative
        error. Additionally, rotations of 180 degrees are equivalent to
        infinitely long vectors. For calculations, a good alternative can
        often be axis/angle pairs.
        """
        axes = Vector3d(axes)
        norms = axes.norm
        angles = np.arctan(norms) * 2

        if np.max(angles) > 179.999:
            raise UserWarning(
                "Maximum angle is greater than 179.999. Rodrigues "
                + "Vectors cannot paramaterize 2-fold rotations. "
                + "Consider an alternative import method."
            )
        if np.min(norms) < np.finfo(norms.dtype).resolution * 1000:
            raise UserWarning(
                "Maximum estimated error is greater than 0.1%."
                + "Rodriguez vectors have increaing associated errors"
                + " for small angle rotations. Consider an alternative "
                + "import method."
            )

        qu = cls.from_axes_angles(axes, angles)
        return qu.unit

    @classmethod
    def from_axes_angles(
        cls,
        axes: Union[np.ndarray, Vector3d, tuple, list],
        angles: Union[np.ndarray, tuple, list, float],
        degrees: bool = False,
    ) -> Quaternion:
        """Create unit quaternions from axis-angle pairs
        :cite:`rowenhorst2015consistent`.

        Parameters
        ----------
        axes
            Axes of rotation.
        angles
            Angles of rotation in radians (``degrees=False``) or degrees
            (``degrees=True``).
        degrees
            If ``True``, the given angles are assumed to be in degrees.
            Default is ``False``.

        Returns
        -------
        q
            Unit quaternions.

        Examples
        --------
        >>> from orix.quaternion import Quaternion
        >>> q = Quaternion.from_axes_angles((0, 0, -1), 90, degrees=True)
        >>> q
        Quaternion (1,)
        [[ 0.7071  0.      0.     -0.7071]]

        See Also
        --------
        from_rodrigues, from_homochoric
        """
        if np.size(axes) == 0:
            return cls.empty()

        axes = Vector3d(axes).unit.data
        angles = np.array(angles)
        if degrees:
            angles = np.deg2rad(angles)

        q = _conversions.ax2qu(axes, angles)
        q = cls(q)
        q = q.unit

        return q

    @classmethod
    def from_homochoric(
        cls,
        ho: Union[Vector3d, Homochoric, np.ndarray, tuple, list],
    ) -> Quaternion:
        r"""Create unit quaternions from homochoric vectors
        :cite:`rowenhorst2015consistent`.

        Parameters
        ----------
        ho
            Homochoric vectors parallel to the axes of rotation with
            lengths equal to
            :math:`\left[\frac{3}{4}\cdot(\theta - \sin(\theta))\right]^{1/3}`,
            where :math:`\theta` is the angle of rotation.

        Returns
        -------
        q
            Unit quaternions.

        See Also
        --------
        from_axes_angles, from_rodrigues
        """
        if np.size(ho) == 0:
            return cls.empty()

        if isinstance(ho, Vector3d):
            ho = ho.data
        else:
            ho = np.atleast_2d(ho)
            if ho.shape[-1] != 3:
                raise ValueError("Final dimension of vector array must be 3.")

        shape = ho.shape[:-1]
        ho = ho.reshape((-1, 3))

        ax = _conversions.ho2ax(ho)
        q = _conversions.ax2qu(ax[:, :3], ax[:, 3])
        q = q.reshape(shape + (4,))
        q = cls(q)
        q = q.unit

        return q

    @classmethod
    def from_rodrigues(
        cls,
        ro: Union[np.ndarray, Vector3d, tuple, list],
        angles: Union[np.ndarray, tuple, list, float, None] = None,
    ) -> Quaternion:
        r"""Create unit quaternions from three component Rodrigues
        vectors :math:`\hat{\mathbf{n}}` or four component
        Rodrigues-Frank vectors :math:`\mathbf{\rho}`
        :cite:`rowenhorst2015consistent`.

        Parameters
        ----------
        ro
            Rodrigues vectors :math:`\hat{\mathbf{n}}` of three
            components. These are the components of the Rodrigues-Frank
            vectors :math:`\mathbf{\rho}` if the angles :math:`\omega`
            are passed.
        angles
            Angles :math:`\omega` of the Rodrigues-Frank vectors
            :math:`\mathbf{\rho}`, one per vector. If these are not
            passed, ``ro`` are the Rodrigues vectors
            :math:`\hat{\mathbf{n}}`.

        Returns
        -------
        q
            Unit quaternions.

        See Also
        --------
        from_axes_angles, from_homochoric

        Notes
        -------
        The Rodrigues-Frank vector :math:`\mathbf{\rho}` is defined as

        .. math::

            \mathbf{\rho} = \hat{\mathbf{n}}\tan\frac{\omega}{2}.

        If the vector length is :math:`\rho = |\mathbf{\rho}|`, the
        angle is given by

        .. math::

            \omega = 2\arctan\rho.

        O. Rodrigues's 1840 vector description was popularized by F. C.
        Frank due to its useful rectilinear mapping of fundamental
        zones, as is well-demonstrated in :cite:`frank1988orientation`.
        However, the length of these vectors, and thus their accuracy,
        scales with :math:`\tan(\omega/2)`. Additionally, two-fold
        rotations produce vectors of infinite length. Thus, Frank and
        others introduced the Rodrigues-Frank vector of length 4,
        consisting of a unit vector followed by the scaling factor
        :math:`\tan(\omega/2)`. This is better suited for storing data
        or performing rotation calculations, as discussed in
        :cite:`rowenhorst2015consistent`.
        """
        if np.size(ro) == 0:
            return cls.empty()

        if isinstance(ro, Vector3d):
            ro = ro.data
        else:
            ro = np.atleast_2d(ro)
            if ro.shape[-1] != 3:
                raise ValueError("Final dimension of vector array must be 3.")

        shape = ro.shape[:-1]
        ro = ro.reshape((-1, 3))

        if angles is None:
            norm = Vector3d(ro).norm
            if np.min(norm) < np.finfo(norm.dtype).resolution * 1000:
                warnings.warn(
                    "Max. estimated error is greater than 0.1%. Rodrigues vectors have "
                    "increasing associated errors for small angle rotations. Consider "
                    "creating quaternions in another way."
                )
            angles = 2 * np.arctan(norm)
            angles = angles[:, np.newaxis]
            ax = np.hstack((ro, angles))
        else:
            angles = angles.ravel()[:, np.newaxis]
            ro_axes_angles = np.hstack((ro, angles))
            ax = _conversions.ro2ax(ro_axes_angles)

        if np.rad2deg(np.max(angles)) > 179.999:
            warnings.warn(
                "Highest angle is greater than 179.999 degrees. Rodrigues vectors "
                "cannot parametrize 2-fold rotations. Consider creating quaternions"
                " in another way."
            )

        q = cls.from_axes_angles(ax[:, :3], ax[:, 3])
        q = q.reshape(*shape)
        q = q.unit

        return q

    # TODO: Remove decorator, **kwargs, and use of "convention" in 0.13
    @classmethod
    @deprecated_argument("convention", "0.9", "0.13", "direction")
    def from_euler(
        cls,
        euler: Union[np.ndarray, tuple, list],
        direction: str = "lab2crystal",
        degrees: bool = False,
        **kwargs,
    ) -> Quaternion:
        """Create unit quaternions from Euler angle sets
        :cite:`rowenhorst2015consistent`.

        Parameters
        ----------
        euler
            Euler angles in radians (``degrees=False``) or in degrees
            (``degrees=True``) in the Bunge convention.
        direction
            Direction of the transformation, either ``"lab2crystal"``
            (default) or the inverse, ``"crystal2lab"``. The former is
            the Bunge convention. Passing ``"MTEX"`` equals the latter.
        degrees
            If ``True``, the given angles are assumed to be in degrees.
            Default is ``False``.

        Returns
        -------
        q
            Unit quaternions.
        """
        direction = direction.lower()
        if direction == "mtex" or (
            "convention" in kwargs and kwargs["convention"] == "mtex"
        ):
            # MTEX' rotations are transformations from the crystal to
            # the lab reference frames. See
            # https://mtex-toolbox.github.io/MTEXvsBungeConvention.html
            # and orix issue #215
            direction = "crystal2lab"

        directions = ["lab2crystal", "crystal2lab"]

        # processing directions
        if direction not in directions:
            raise ValueError(
                f"The chosen direction is not one of the allowed options {directions}"
            )

        if degrees:
            euler = np.deg2rad(euler)

        eu = np.atleast_2d(euler)
        if np.any(np.abs(eu) > 4 * np.pi):
            warnings.warn("Angles are quite high, did you forget to set degrees=True?")

        q = _conversions.eu2qu(eu)
        q = cls(q)

        if direction == "crystal2lab":
            q = ~q

        return q

    @classmethod
    def from_matrix(cls, matrix: Union[np.ndarray, tuple, list]) -> Quaternion:
        """Create unit quaternions from orientation matrices
        :cite:`rowenhorst2015consistent`.

        Parameters
        ----------
        matrix
            Sequence of orientation matrices with the last two
            dimensions of shape ``(3, 3)``.

        Returns
        -------
        q
            Unit quaternions.

        Examples
        --------
        >>> from orix.quaternion import Quaternion
        >>> q = Quaternion.from_matrix([np.eye(3), 2 * np.eye(3), np.diag([1, -1, -1])])
        >>> q
        Quaternion (3,)
        [[1. 0. 0. 0.]
         [1. 0. 0. 0.]
         [0. 1. 0. 0.]]
        """
        # Verify the input can be interpreted as an array of (3, 3) arrays
        om = np.atleast_2d(matrix)
        if om.shape[-2:] != (3, 3):
            raise ValueError("the last two dimensions of 'matrix' must be (3, 3)")

        q = _conversions.om2qu(om)
        q = cls(q)

        return q

    @classmethod
    def from_scipy_rotation(cls, rotation: SciPyRotation) -> Quaternion:
        """Create unit quaternions from
        :class:`scipy.spatial.transform.Rotation`.

        Parameters
        ----------
        rotation
            SciPy rotations.

        Returns
        -------
        quaternion
            Quaternions.

        Notes
        -----
        The SciPy rotation is inverted to be consistent with the orix
        framework of passive rotations.

        While orix represents quaternions with the scalar as the first
        parameter, SciPy has the scalar as the last parameter.

        Examples
        --------
        >>> from orix.quaternion import Quaternion
        >>> from orix.vector import Vector3d
        >>> from scipy.spatial.transform import Rotation as SciPyRotation

        SciPy and orix represent quaternions differently

        >>> r_scipy = SciPyRotation.from_euler("ZXZ", [90, 0, 0], degrees=True)
        >>> r_scipy.as_quat()
        array([0.        , 0.        , 0.70710678, 0.70710678])
        >>> q = Quaternion.from_scipy_rotation(r_scipy)
        >>> q
        Quaternion (1,)
        [[ 0.7071  0.      0.     -0.7071]]
        >>> ~q
        Quaternion (1,)
        [[ 0.7071 -0.     -0.      0.7071]]

        SciPy and orix rotate vectors differently

        >>> v = [1, 1, 0]
        >>> r_scipy.apply(v)
        array([-1.,  1.,  0.])
        >>> q * Vector3d(v)
        Vector3d (1,)
        [[ 1. -1.  0.]]
        >>> ~q * Vector3d(v)
        Vector3d (1,)
        [[-1.  1.  0.]]
        """
        matrix = rotation.inv().as_matrix()
        return cls.from_matrix(matrix=matrix)

    @classmethod
    def from_align_vectors(
        cls,
        other: Union[Vector3d, tuple, list],
        initial: Union[Vector3d, tuple, list],
        weights: Optional[np.ndarray] = None,
        return_rmsd: bool = False,
        return_sensitivity: bool = False,
    ) -> Union[
        Quaternion,
        Tuple[Quaternion, float],
        Tuple[Quaternion, np.ndarray],
        Tuple[Quaternion, float, np.ndarray],
    ]:
        """Estimate a quaternion to optimally align two sets of vectors.

        This method wraps
        :meth:`~scipy.spatial.transform.Rotation.align_vectors`. See
        that method for further explanations of parameters and returns.

        Parameters
        ----------
        other
            Vectors of shape ``(n,)`` in the other reference frame.
        initial
            Vectors of shape ``(n,)`` in the initial reference frame.
        weights
            Relative importance of the different vectors.
        return_rmsd
            Whether to return the (weighted) root mean square distance
            between ``other`` and ``initial`` after alignment. Default
            is ``False``.
        return_sensitivity
            Whether to return the sensitivity matrix. Default is
            ``False``.

        Returns
        -------
        estimated_quaternion
            Best estimate of the quaternion that transforms ``initial``
            to ``other``.
        rmsd
            Returned when ``return_rmsd=True``.
        sensitivity
            Returned when ``return_sensitivity=True``.

        Examples
        --------
        >>> from orix.quaternion import Quaternion
        >>> from orix.vector import Vector3d
        >>> v1 = Vector3d([[1, 0, 0], [0, 1, 0]])
        >>> v2 = Vector3d([[0, -1, 0], [0, 0, 1]])
        >>> q12 = Quaternion.from_align_vectors(v2, v1)
        >>> q12 * v1
        Vector3d (2,)
        [[ 0. -1.  0.]
         [ 0.  0.  1.]]
        >>> q21, dist = Quaternion.from_align_vectors(v1, v2, return_rmsd=True)
        >>> dist
        0.0
        >>> q21 * v2
        Vector3d (2,)
        [[1. 0. 0.]
         [0. 1. 0.]]
        """
        if not isinstance(other, Vector3d):
            other = Vector3d(other)
        if not isinstance(initial, Vector3d):
            initial = Vector3d(initial)
        vec1 = initial.unit.data
        vec2 = other.unit.data

        out = SciPyRotation.align_vectors(
            vec1, vec2, weights=weights, return_sensitivity=return_sensitivity
        )
        out = list(out)
        out[0] = cls.from_scipy_rotation(out[0])

        if not return_rmsd:
            del out[1]

        return out[0] if len(out) == 1 else tuple(out)

    # ------------------- Additional class methods ------------------- #

    @classmethod
    def triple_cross(cls, q1: Quaternion, q2: Quaternion, q3: Quaternion) -> Quaternion:
        """Pointwise cross product of three quaternions.

        Parameters
        ----------
        q1
            First quaternions.
        q2
            Second quaternions.
        q3
            Third quaternions.

        Returns
        -------
        q
            Quaternions resulting from the triple cross product.
        """
        q1a, q1b, q1c, q1d = q1.a, q1.b, q1.c, q1.d
        q2a, q2b, q2c, q2d = q2.a, q2.b, q2.c, q2.d
        q3a, q3b, q3c, q3d = q3.a, q3.b, q3.c, q3.d
        # fmt: off
        a = (
            + q1b * q2c * q3d
            - q1b * q3c * q2d
            - q2b * q1c * q3d
            + q2b * q3c * q1d
            + q3b * q1c * q2d
            - q3b * q2c * q1d
        )
        b = (
            + q1a * q3c * q2d
            - q1a * q2c * q3d
            + q2a * q1c * q3d
            - q2a * q3c * q1d
            - q3a * q1c * q2d
            + q3a * q2c * q1d
        )
        c = (
            + q1a * q2b * q3d
            - q1a * q3b * q2d
            - q2a * q1b * q3d
            + q2a * q3b * q1d
            + q3a * q1b * q2d
            - q3a * q2b * q1d
        )
        d = (
            + q1a * q3b * q2c
            - q1a * q2b * q3c
            + q2a * q1b * q3c
            - q2a * q3b * q1c
            - q3a * q1b * q2c
            + q3a * q2b * q1c
        )
        # fmt: on
        q = cls(np.vstack((a, b, c, d)).T)
        return q

    @classmethod
    def random(cls, shape: Union[int, tuple] = (1,)) -> Quaternion:
        """Create random unit quaternions.

        Parameters
        ----------
        shape
            Shape of the quaternion instance.

        Returns
        -------
        q
            Unit quaternions.
        """
        shape = (shape,) if isinstance(shape, int) else shape
        n = int(np.prod(shape))
        q = []
        while len(q) < n:
            r = np.random.uniform(-1, 1, (3 * n, cls.dim))
            r2 = np.sum(np.square(r), axis=1)
            r = r[np.logical_and(1e-9**2 < r2, r2 <= 1)]
            q += list(r)
        q = cls(np.array(q[:n]))
        q = q.unit
        q = q.reshape(*shape)
        return q

    @classmethod
    def identity(cls, shape: Union[int, tuple] = (1,)) -> Quaternion:
        """Return identity quaternions.

        Parameters
        ----------
        shape
            Shape of the quaternion instance.

        Returns
        -------
        q
            Identity quaternions.
        """
        shape = (shape,) if isinstance(shape, int) else shape
        q = np.zeros(shape + (4,))
        q[..., 0] = 1
        return cls(q)

    # --------------------- All "to_*" functions --------------------- #

    # TODO: Remove decorator and **kwargs in 0.13
    @deprecated_argument("convention", since="0.9", removal="0.13")
    def to_euler(self, degrees: bool = False, **kwargs) -> np.ndarray:
        r"""Return the unit quaternions as Euler angles in the Bunge
        convention :cite:`rowenhorst2015consistent`.

        Parameters
        ----------
        degrees
            If ``True``, the given angles are returned in degrees.
            Default is ``False``.

        Returns
        -------
        eu
            Array of Euler angles in radians (``degrees=False``) or
            degrees (``degrees=True``), in the ranges
            :math:`\phi_1 \in [0, 2\pi]`, :math:`\Phi \in [0, \pi]`, and
            :math:`\phi_1 \in [0, 2\pi]`.
        """
        eu = _conversions.qu2eu(self.unit.data)
        if degrees:
            eu = np.rad2deg(eu)
        return eu

    def to_matrix(self) -> np.ndarray:
        """Return the unit quaternions as orientation matrices
        :cite:`rowenhorst2015consistent`.

        Returns
        -------
        om
            Array of orientation matrices after normalizing the
            quaternions.

        Examples
        --------
        >>> from orix.quaternion import Quaternion
        >>> q1 = Quaternion([[1, 0, 0, 0], [2, 0, 0, 0]])
        >>> np.allclose(q1.to_matrix(), np.eye(3))
        True
        >>> q2 = Quaternion([[0, 1, 0, 0], [0, 2, 0, 0]])
        >>> np.allclose(q2.to_matrix(), np.diag([1, -1, -1]))
        True
        """
        om = _conversions.qu2om(self.unit.data)
        return om

    def to_axes_angles(self) -> AxAngle:
        r"""Return the unit quaternions as axis-angle vectors
        :cite:`rowenhorst2015consistent`.

        Returns
        -------
        ax
            Axis-angle vectors with magnitude :math:`\theta` equal to
            the angle of rotation.

        See Also
        --------
        to_homochoric, to_rodrigues

        Examples
        --------
        A 3-fold rotation around the [111] axis

        >>> from orix.quaternion import Quaternion
        >>> q = Quaternion([0.5, 0.5, 0.5, 0.5])
        >>> ax = q.to_axes_angles()
        >>> ax
        AxAngle (1,)
        [[1.2092 1.2092 1.2092]]
        >>> np.rad2deg(ax.angle)
        array([120.])
        """
        axes, angles = _conversions.qu2ax(self.unit.data)
        ax = AxAngle(axes * angles)
        return ax

    def to_rodrigues(self, frank: bool = False) -> Union[Rodrigues, np.ndarray]:
        r"""Return the unit quaternions as Rodrigues or Rodrigues-Frank
         vectors :cite:`rowenhorst2015consistent`.

        Parameters
        ----------
        frank
            Whether to return Rodrigues vectors scaled by
            :math:`\tan(\theta/2)`, where :math:`\theta` is the angle of
            rotation, or Rodrigues-Frank vectors scaled by
            :math:`\omega = 2\arctan(|\rho|)` in an array.

        Returns
        -------
        ro
            Vectors :math:`\hat{\mathbf{n}}` parallel to the axis of
            rotation if ``frank=False`` or an array of four-component
            vectors if ``frank=True``.

        See Also
        --------
        to_axes_angles, to_homochoric

        Examples
        --------
        A 3-fold rotation around the [111] axis

        >>> from orix.quaternion import Quaternion
        >>> q = Quaternion.from_axes_angles([1, 1, 1], 120, degrees=True)
        >>> ro1 = q.to_rodrigues()
        >>> ro1
        Rodrigues (1,)
        [[1. 1. 1.]]
        >>> ro1.norm
        array([1.73205081])
        >>> ro2 = q.to_rodrigues(frank=True)
        >>> ro2
        array([[0.57735027, 0.57735027, 0.57735027, 1.73205081]])
        >>> np.linalg.norm(ro2[:, :3])
        1.0

        A 45:math:`\degree` rotation around the [111] axis

        >>> q2 = Quaternion.from_axes_angles([1, 1, 1], 45, degrees=True)
        >>> ro3 = q2.to_rodrigues()
        >>> ro3
        Rodrigues (1,)
        [[0.2391 0.2391 0.2391]]

        Notes
        -----
        Rodrigues vectors, originally proposed by O. Rodrigues, are
        often used for plotting orientations as they create isomorphic
        (though not volume-preserving) plots and form fundamental zones
        with rectilinear boundaries. These features are
        well-demonstrated in :cite:`frank1988orientation`. See
        :cite:`rowenhorst2015consistent` for examples of usage of
        Rodrigues-Frank vectors.
        """
        q = self.unit
        if not frank:
            ro = q.axis * np.tan(self.angle / 2)
            ro = Rodrigues(ro)
        else:
            axes, angles = _conversions.qu2ax(q.data)
            axes_angles = np.concatenate((axes, angles), axis=-1)
            ro = _conversions.ax2ro(axes_angles)
        return ro

    def to_homochoric(self) -> Homochoric:
        r"""Return the unit quaternions as homochoric vectors
        :cite:`rowenhorst2015consistent`.

        Returns
        -------
        ho
            Homochoric vectors parallel to the axes of rotation with
            lengths equal to
            :math:`\left[\frac{3}{4}\cdot(\theta - \sin(\theta))\right]^{1/3}`,
            where :math:`\theta` is the angle of rotation.

        See Also
        --------
        to_axes_angles, from_rodrigues

        Examples
        --------
        A 3-fold rotation about the [111] axis

        >>> from orix.quaternion import Quaternion
        >>> q = Quaternion.from_axes_angles([1, 1, 1], 120, degrees=True)
        >>> ho = q.to_homochoric()
        >>> ho
        Homochoric (1,)
        [[0.5618 0.5618 0.5618]]

        Notes
        -----
        Homochoric vectors are often used for plotting orientations as
        they create an isomorphic (though not angle-preserving) mapping
        from the non-euclidean orientation space into Cartesian
        coordinates. Additionally, unlike Rodrigues vectors, all
        rotations map into a finite space, bounded by a sphere of radius
        :math:`\pi`.
        """
        ho = _conversions.qu2ho(self.unit.data)
        ho = Homochoric(ho)
        return ho

    # -------------------- Other public functions ------------------- #

    def dot(self, other: Quaternion) -> np.ndarray:
        """Return the dot products of the quaternions and the other
        quaternions.

        Parameters
        ----------
        other
            Other quaternions.

        Returns
        -------
        dot_products
            Dot products.

        See Also
        --------
        Rotation.dot
        Orientation.dot

        Examples
        --------
        >>> from orix.quaternion import Quaternion
        >>> q1 = Quaternion([[1, 0, 0, 0], [0.9239, 0, 0, 0.3827]])
        >>> q2 = Quaternion([[0.9239, 0, 0, 0.3827], [0.7071, 0, 0, 0.7071]])
        >>> q1.dot(q2)
        array([0.9239    , 0.92389686])
        """
        return np.sum(self.data * other.data, axis=-1)

    def dot_outer(self, other: Quaternion) -> np.ndarray:
        """Return the dot products of all quaternions to all the other
        quaternions.

        Parameters
        ----------
        other
            Other quaternions.

        Returns
        -------
        dot_products
            Dot products.

        See Also
        --------
        Rotation.dot_outer
        Orientation.dot_outer

        Examples
        --------
        >>> from orix.quaternion import Quaternion
        >>> q1 = Quaternion([[1, 0, 0, 0], [0.9239, 0, 0, 0.3827]])
        >>> q2 = Quaternion([[0.9239, 0, 0, 0.3827], [0.7071, 0, 0, 0.7071]])
        >>> q1.dot_outer(q2)
        array([[0.9239    , 0.7071    ],
               [1.0000505 , 0.92389686]])
        """
        dots = np.tensordot(self.data, other.data, axes=(-1, -1))
        return dots

    def mean(self) -> Quaternion:
        """Return the mean quaternion with unitary weights.

        Returns
        -------
        quat_mean
            Mean quaternion.

        Notes
        -----
        The method used here corresponds to Equation (13) in
        https://arc.aiaa.org/doi/pdf/10.2514/1.28949.
        """
        q = self.flatten().data.T
        qq = q.dot(q.T)
        w, v = np.linalg.eig(qq)
        w_max = np.argmax(w)
        return self.__class__(v[:, w_max])

    def outer(
        self,
        other: Union[Quaternion, Vector3d],
        lazy: bool = False,
        chunk_size: int = 20,
        progressbar: bool = True,
    ) -> Union[Quaternion, Vector3d]:
        """Return the outer products of the quaternions and the other
        quaternions or vectors.

        Parameters
        ----------
        other
            Another orientation or vector.
        lazy
            Whether to computer this computation using Dask. This option
            can be used to reduce memory usage when working with large
            arrays. Default is ``False``.
        chunk_size
            When using ``lazy`` computation, ``chunk_size`` represents
            the number of objects per axis for each input to include in
            each iteration of the computation. Default is 20.
        progressbar
            Whether to show a progressbar during computation if
            ``lazy=True``. Default is ``True``.

        Returns
        -------
        out
            Outer products.

        Raises
        ------
        NotImplementedError
            If ``other`` is not a quaternion, 3D vector, or a Miller
            index.
        """
        if isinstance(other, Quaternion):
            if lazy:
                darr = self._outer_dask(other, chunk_size=chunk_size)
                arr = np.empty(darr.shape)
                if progressbar:
                    with ProgressBar():
                        da.store(darr, arr)
                else:
                    da.store(darr, arr)
            else:
                q1 = quaternion.from_float_array(self.data)
                q2 = quaternion.from_float_array(other.data)
                # np.outer works with flattened array
                q = np.outer(q1, q2).reshape(q1.shape + q2.shape)
                arr = quaternion.as_float_array(q)
            return other.__class__(arr)
        elif isinstance(other, Vector3d):
            if lazy:
                darr = self._outer_dask(other, chunk_size=chunk_size)
                arr = np.empty(darr.shape)
                if progressbar:
                    with ProgressBar():
                        da.store(darr, arr)
                else:
                    da.store(darr, arr)
            else:
                q = quaternion.from_float_array(self.data)
                arr = quaternion.rotate_vectors(q, other.data)
            if isinstance(other, Miller):
                m = other.__class__(xyz=arr, phase=other.phase)
                m.coordinate_format = other.coordinate_format
                return m
            else:
                return other.__class__(arr)
        else:
            raise NotImplementedError(
                "This operation is currently not avaliable in orix, please use outer "
                "with `other` of type `Quaternion` or `Vector3d`"
            )

    # ------------------- Other private functions ------------------- #

    def _outer_dask(
        self, other: Union[Quaternion, Vector3d], chunk_size: int = 20
    ) -> da.Array:
        """Compute the product of every quaternion in this instance to
        every quaternion or vector in another instance, returned as a
        Dask array.

        For quaternion-quaternion multiplication, this is known as the
        Hamilton product.

        Parameters
        ----------
        other
            Another orientation or vector.
        chunk_size
            Number of objects per axis for each input to include in each
            iteration of the computation. Default is 20.

        Returns
        -------
        out

        Raises
        ------
        TypeError
            If ``other`` is not a quaternion or a vector.

        Notes
        -----
        For quaternion-quaternion multiplication, to create a new
        quaternion from the returned array ``out``, do
        ``q = Quaternion(out.compute())``. Likewise for
        quaternion-vector multiplication, to create a new vector from
        the returned array do ``v = Vector3d(out.compute())``.
        """
        if not isinstance(other, (Quaternion, Vector3d)):
            raise TypeError("Other must be Quaternion or Vector3d.")

        ndim1 = len(self.shape)
        ndim2 = len(other.shape)

        # Set chunk sizes
        chunks1 = (chunk_size,) * ndim1 + (-1,)
        chunks2 = (chunk_size,) * ndim2 + (-1,)

        # Dask has no dask.multiply.outer(), use dask.array.einsum
        # Summation subscripts
        str1 = "abcdefghijklm"[:ndim1]  # Max. object dimension of 13
        str2 = "nopqrstuvwxyz"[:ndim2]
        sum_over = f"...{str1},{str2}...->{str1 + str2}"

        # Get quaternion parameters as dask arrays to be computed later
        q1 = da.from_array(self.data, chunks=chunks1)
        a1, b1, c1, d1 = q1[..., 0], q1[..., 1], q1[..., 2], q1[..., 3]

        # We silence dask's einsum performance warnings for "small"
        # chunk sizes, since using the chunk sizes suggested floods
        # memory
        warnings.filterwarnings("ignore", category=da.PerformanceWarning)

        if isinstance(other, Quaternion):
            q2 = da.from_array(other.data, chunks=chunks2)
            a2, b2, c2, d2 = q2[..., 0], q2[..., 1], q2[..., 2], q2[..., 3]
            # fmt: off
            a = (
                + da.einsum(sum_over, a1, a2)
                - da.einsum(sum_over, b1, b2)
                - da.einsum(sum_over, c1, c2)
                - da.einsum(sum_over, d1, d2)
            )
            b = (
                + da.einsum(sum_over, b1, a2)
                + da.einsum(sum_over, a1, b2)
                - da.einsum(sum_over, d1, c2)
                + da.einsum(sum_over, c1, d2)
            )
            c = (
                + da.einsum(sum_over, c1, a2)
                + da.einsum(sum_over, d1, b2)
                + da.einsum(sum_over, a1, c2)
                - da.einsum(sum_over, b1, d2)
            )
            d = (
                + da.einsum(sum_over, d1, a2)
                - da.einsum(sum_over, c1, b2)
                + da.einsum(sum_over, b1, c2)
                + da.einsum(sum_over, a1, d2)
            )
            # fmt: on
            out = da.stack([a, b, c, d], axis=-1)
        else:  # Vector3d
            v2 = da.from_array(other.data, chunks=chunks2)
            x2, y2, z2 = v2[..., 0], v2[..., 1], v2[..., 2]
            # fmt: off
            x = (
                + da.einsum(sum_over, a1**2 + b1**2 - c1**2 - d1**2, x2)
                + da.einsum(sum_over, a1 * c1 + b1 * d1, z2) * 2
                + da.einsum(sum_over, b1 * c1 - a1 * d1, y2) * 2
            )
            y = (
                + da.einsum(sum_over, a1**2 - b1**2 + c1**2 - d1**2, y2)
                + da.einsum(sum_over, a1 * d1 + b1 * c1, x2) * 2
                + da.einsum(sum_over, c1 * d1 - a1 * b1, z2) * 2
            )
            z = (
                + da.einsum(sum_over, a1**2 - b1**2 - c1**2 + d1**2, z2)
                + da.einsum(sum_over, a1 * b1 + c1 * d1, y2) * 2
                + da.einsum(sum_over, b1 * d1 - a1 * c1, x2) * 2
            )
            # fmt: on
            out = da.stack([x, y, z], axis=-1)

        new_chunks = tuple(chunks1[:-1]) + tuple(chunks2[:-1]) + (-1,)

        return out.rechunk(new_chunks)
