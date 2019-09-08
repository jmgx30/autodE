import numpy as np
from copy import deepcopy
from autode.config import Config
from autode.log import logger
from autode.ts_guess import TSguess
from autode.plotting import plot_1dpes
from autode.constants import Constants
from autode.calculation import Calculation
from autode.wrappers.ORCA import ORCA
from autode.wrappers.XTB import XTB


def get_ts_guess_1dpes_scan(mol, active_bond, n_steps, name, reaction_class, method, keywords, delta_dist=1.5,
                            active_bonds_not_scanned=None):
    """
    Scan the distance between 2 atoms and return the xyzs with peak energy
    :param mol: Molecule object
    :param active_bond: (tuple) of atom ids
    :param method: (object) electronic structure method
    :param keywords (list) list of keywords required by an electronic structure method
    :param delta_dist: (float) Distance to add onto the current distance (Å)
    :param n_steps: (int) Number of scan steps to use in the XTB scan
    :param name: (str) Name of reaction
    :param reaction_class: (object) class of the reaction (reactions.py)
    :param active_bonds_not_scanned: list(tuple) pairs of atoms that are active, but will not be scanned in the 1D PES
    :return: List of xyzs
    """
    logger.info('Getting TS guess from 1D relaxed potential energy scan')
    mol_with_const = deepcopy(mol)

    curr_dist = mol.calc_bond_distance(active_bond)
    # Generate a list of distances at which to constrain the optimisation
    dists = np.linspace(curr_dist, curr_dist + delta_dist, n_steps)
    # Initialise an empty dictionary containing the distance as a key and the xyzs and energy as s tuple value
    xyzs_list, energy_list = [], []

    # Run a relaxed potential energy surface scan by running sequential constrained optimisations
    for n, dist in enumerate(dists):
        const_opt = Calculation(name=name + '_scan' + str(n), molecule=mol_with_const, method=method, opt=True,
                                n_cores=Config.n_cores, distance_constraints={active_bond: dist}, keywords=keywords)
        const_opt.run()
        xyzs = const_opt.get_final_xyzs()
        xyzs_list.append(xyzs)
        energy_list.append(const_opt.get_energy())

        # Update the molecule with constraints xyzs such that the next optimisation is as fast as possible
        mol_with_const.xyzs = xyzs

    # Make a new molecule that will form the basis of the TS guess object
    tsguess_mol = deepcopy(mol)
    tsguess_mol.set_xyzs(xyzs=find_1dpes_maximum_energy_xyzs(dists, xyzs_list, energy_list))

    if tsguess_mol.xyzs is None:
        logger.warning('TS guess had no xyzs')
        return None

    active_bonds = [active_bond] if active_bonds_not_scanned is None else [active_bond] + active_bonds_not_scanned

    return TSguess(name=name, reaction_class=reaction_class, molecule=tsguess_mol, active_bonds=active_bonds)


def find_1dpes_maximum_energy_xyzs(dists, xyzs_list, energy_list):
    """
    Given a 1D list of energies find the maximum that between the end points
    :param dists: (dict) [value] = (xyzs, energy)
    :return:
    """

    logger.info('Finding peak in 1D PES')

    xyzs_peak_energy = None
    if len(xyzs_list) == 0 or len(energy_list) == 0:
        logger.error('Had no distances, xyzs and energies')
        return None

    peak_e, min_e = min(energy_list), min(energy_list)

    for i in range(1, len(dists) - 1):
        if energy_list[i] > peak_e and energy_list[i-1] < energy_list[i] > energy_list[i+1]:
            peak_e = energy_list[i]
            xyzs_peak_energy = xyzs_list[i]

    plot_1dpes(dists, [Constants.ha2kcalmol * (e - min_e) for e in energy_list])

    if peak_e != min_e:
        logger.info('Energy at peak in PES at ∆E = {} kcal/mol'.format(Constants.ha2kcalmol * (peak_e - min_e)))
    else:
        logger.warning('Couldn\'t find a peak in the PES')

    return xyzs_peak_energy

