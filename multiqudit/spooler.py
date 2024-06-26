"""
The module that contains all the necessary logic for the multiqudit.
"""

from typing import List

import numpy as np
from scipy.sparse import identity, diags, csc_matrix
from scipy import sparse
from scipy.sparse.linalg import expm_multiply

from sqooler.spoolers import create_memory_data
from sqooler.schemes import ExperimentDict, ExperimentalInputDict


def op_at_wire(op: csc_matrix, pos: int, dim_per_wire: List[int]) -> csc_matrix:
    """
    Applies an operation onto the wire and provides unitaries on the other wires.
    Basically this creates the nice tensor products.

    Args:
        op (matrix): The operation that should be applied.
        pos (int): The wire onto which the operation should be applied.
        dim_per_wire (int): What is the local Hilbert space of each wire.

    Returns:
        The tensor product matrix.
    """
    # There are two cases the first wire can be the identity or not
    if pos == 0:
        res = op
    else:
        res = csc_matrix(identity(dim_per_wire[0]))
    # then loop for the rest
    for i1 in np.arange(1, len(dim_per_wire)):
        temp = csc_matrix(identity(dim_per_wire[i1]))
        if i1 == pos:
            temp = op
        res = sparse.kron(res, temp)

    return res


def gen_circuit(exp_name: str, json_dict: ExperimentalInputDict) -> ExperimentDict:
    """The function the creates the instructions for the circuit.
    json_dict: The list of instructions for the specific run.
    """
    # pylint: disable=R0914
    ins_list = json_dict.instructions
    n_shots = json_dict.shots
    if json_dict.seed is not None:
        np.random.seed(json_dict.seed)

    n_wires = json_dict.num_wires
    spin_per_wire = 1 / 2 * np.ones(n_wires)

    for ins in ins_list:
        if ins.name == "load":
            spin_per_wire[ins.wires[0]] = 1 / 2 * ins.params[0]

    dim_per_wire = 2 * spin_per_wire + np.ones(n_wires)
    dim_per_wire = dim_per_wire.astype(int)
    dim_hilbert = np.prod(dim_per_wire)

    # we will need a list of local spin operators as their dimension can change
    # on each wire
    lx_list = []
    ly_list = []
    lz_list = []
    lz2_list = []

    for i1 in np.arange(0, n_wires):
        # let's put together spin matrices
        spin_length = spin_per_wire[i1]
        qudit_range = np.arange(spin_length, -(spin_length + 1), -1)

        lx = csc_matrix(
            1
            / 2
            * diags(
                [
                    np.sqrt(
                        [
                            (spin_length - m + 1) * (spin_length + m)
                            for m in qudit_range[:-1]
                        ]
                    ),
                    np.sqrt(
                        [
                            (spin_length + m + 1) * (spin_length - m)
                            for m in qudit_range[1:]
                        ]
                    ),
                ],
                [-1, 1],
            )
        )
        ly = csc_matrix(
            1
            / (2 * 1j)
            * diags(
                [
                    np.sqrt(
                        [
                            (spin_length - m + 1) * (spin_length + m)
                            for m in qudit_range[:-1]
                        ]
                    ),
                    -1
                    * np.sqrt(
                        [
                            (spin_length + m + 1) * (spin_length - m)
                            for m in qudit_range[1:]
                        ]
                    ),
                ],
                [-1, 1],
            )
        )
        lz = csc_matrix(diags([qudit_range], [0]))
        lz2 = lz.dot(lz)

        lx_list.append(op_at_wire(lx, i1, list(dim_per_wire)))
        ly_list.append(op_at_wire(ly, i1, list(dim_per_wire)))
        lz_list.append(op_at_wire(lz, i1, list(dim_per_wire)))
        lz2_list.append(op_at_wire(lz2, i1, list(dim_per_wire)))

    initial_state = 1j * np.zeros(dim_per_wire[0])
    initial_state[0] = 1 + 1j * 0
    psi = sparse.csc_matrix(initial_state)
    for i1 in np.arange(1, len(dim_per_wire)):
        initial_state = 1j * np.zeros(dim_per_wire[i1])
        initial_state[0] = 1 + 1j * 0
        psi = sparse.kron(psi, initial_state)
    psi = psi.T

    measurement_indices = []
    shots_array = []
    for inst in ins_list:
        if inst.name == "rlx":
            position = inst.wires[0]
            theta = inst.params[0]
            psi = expm_multiply(-1j * theta * lx_list[position], psi)
        if inst.name == "rly":
            position = inst.wires[0]
            theta = inst.params[0]
            psi = expm_multiply(-1j * theta * ly_list[position], psi)
        if inst.name == "rlz":
            position = inst.wires[0]
            theta = inst.params[0]
            psi = expm_multiply(-1j * theta * lz_list[position], psi)
        if inst.name == "rlz2":
            position = inst.wires[0]
            theta = inst.params[0]
            psi = expm_multiply(-1j * theta * lz2_list[position], psi)
        if inst.name == "rlxly":
            # apply gate on two qudits
            if len(inst.wires) == 2:
                position1 = inst.wires[0]
                position2 = inst.wires[1]
                theta = inst.params[0]
                lp1 = lx_list[position1] + 1j * ly_list[position1]
                lp2 = lx_list[position2] + 1j * ly_list[position2]
                lxly = lp1.dot(lp2.conjugate().T)
                lxly = lxly + lxly.conjugate().T
                psi = expm_multiply(-1j * theta * lxly, psi)
            # apply gate on all qudits
            elif len(inst.wires) == n_wires:
                theta = inst.params[0]
                lxly = csc_matrix((dim_hilbert, dim_hilbert))
                for i1 in np.arange(0, n_wires - 1):
                    lp1 = lx_list[i1] + 1j * ly_list[i1]
                    lp2 = lx_list[i1 + 1] + 1j * ly_list[i1 + 1]
                    lxly = lxly + lp1.dot(lp2.conjugate().T)
                lxly = lxly + lxly.conjugate().T
                psi = expm_multiply(-1j * theta * lxly, psi)
        if inst.name == "rlzlz":
            # apply gate on two quadits
            if len(inst.wires) == 2:
                position1 = inst.wires[0]
                position2 = inst.wires[1]
                theta = inst.params[0]
                lzlz = lz_list[position1].dot(lz_list[position2])
                psi = expm_multiply(-1j * theta * lzlz, psi)
        if inst.name == "multiqudit_full":
            omega, delta, chi, jxy, jzz = inst.params
            u_full = csc_matrix((dim_hilbert, dim_hilbert))
            # first the RX
            for lxi in lx_list:
                u_full = u_full + omega * lxi
            # next the RZ
            for lzi in lz_list:
                u_full = u_full + delta * lzi
            # next the local squeezing
            for lz2i in lz2_list:
                u_full = u_full + chi * lz2i
            # next the neighboring flip-flop
            for ii in range(n_wires - 1):
                position1 = ii
                position2 = ii + 1
                lp1 = lx_list[position1] + 1j * ly_list[position1]
                lp2 = lx_list[position2] + 1j * ly_list[position2]
                lxly = lp1.dot(lp2.conjugate().T)
                lxly = lxly + lxly.conjugate().T
                u_full = u_full + jxy * lxly
            # next the neighboring zz
            for ii in range(n_wires - 1):
                lzlz = lz_list[ii].dot(lz_list[ii + 1])
                u_full = u_full + jzz * lzlz
            psi = expm_multiply(-1j * u_full, psi)
        if inst.name == "measure":
            measurement_indices.append(inst.wires[0])
    if measurement_indices:
        # the following filters out the results for the indices we prefer.
        probs = np.squeeze(abs(psi.toarray()) ** 2)
        result_ind = np.random.choice(dim_hilbert, p=probs, size=n_shots)
        measurements = np.zeros((n_shots, len(measurement_indices)), dtype=int)
        for i1 in range(n_shots):
            observed = np.unravel_index(result_ind[i1], dim_per_wire)
            # TODO these types are messed up for the moment
            # as ususal we add an ignore until this gets back to bite us in the ...
            # but it simply to tough to find out where the typing goes wrong right now.
            observed = np.array(observed)  # type: ignore
            measurements[i1, :] = observed[measurement_indices]  # type: ignore
        shots_array = measurements.tolist()

    exp_sub_dict = create_memory_data(shots_array, exp_name, n_shots, ins_list)
    return exp_sub_dict
