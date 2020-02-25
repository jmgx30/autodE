from autode.config import Config
from autode.log import logger
from autode.constants import Constants
from autode.wrappers.base import ElectronicStructureMethod
from autode.wrappers.base import req_methods
import numpy as np
import os

vdw_gaussian_solvent_dict = {'water': 'Water', 'acetone': 'Acetone', 'acetonitrile': 'Acetonitrile', 'benzene': 'Benzene',
                             'carbon tetrachloride': 'CCl4', 'dichloromethane': 'CH2Cl2', 'chloroform': 'Chloroform', 'cyclohexane': 'Cyclohexane',
                             'n,n-dimethylformamide': 'DMF', 'dimethylsulfoxide': 'DMSO', 'ethanol': 'Ethanol', 'n-hexane': 'Hexane',
                             'methanol': 'Methanol', '1-octanol': 'Octanol', 'pyridine': 'Pyridine', 'tetrahydrofuran': 'THF', 'toluene': 'Toluene'}

ORCA = ElectronicStructureMethod(name='orca', path=Config.ORCA.path,
                                 scan_keywords=Config.ORCA.scan_keywords,
                                 conf_opt_keywords=Config.ORCA.conf_opt_keywords,
                                 gradients_keywords=Config.ORCA.gradients_keywords,
                                 sp_grad_keywords=Config.ORCA.sp_grad_keywords,
                                 opt_keywords=Config.ORCA.opt_keywords,
                                 opt_ts_keywords=Config.ORCA.opt_ts_keywords,
                                 hess_keywords=Config.ORCA.hess_keywords,
                                 opt_ts_block=Config.ORCA.opt_ts_block,
                                 sp_keywords=Config.ORCA.sp_keywords)

ORCA.__name__ = 'ORCA'


def generate_input(calc):
    calc.input_filename = calc.name + '_orca.inp'
    calc.output_filename = calc.name + '_orca.out'
    keywords = calc.keywords.copy()

    opt_or_sp = False

    for keyword in keywords:
        if 'opt' in keyword.lower():
            if keyword.lower() != 'optts':
                opt_or_sp = True
            if calc.n_atoms == 1:
                logger.warning('Cannot do an optimisation for a single atom')
                keywords.remove(keyword)
        if keyword.lower() == 'sp':
            opt_or_sp = True
        if keyword.lower() == 'freq':
            if calc.partial_hessian:
                keywords.remove(keyword)
                keywords.append('NumFreq')

    if opt_or_sp and calc.solvent_keyword in vdw_gaussian_solvent_dict.keys():
        keywords.append(f'CPCM({vdw_gaussian_solvent_dict[calc.solvent_keyword]})')

    with open(calc.input_filename, 'w') as inp_file:
        print('!', *keywords, file=inp_file)

        if calc.solvent_keyword:
            if calc.solvent_keyword in vdw_gaussian_solvent_dict.keys() and opt_or_sp:
                print('%cpcm\n surfacetype vdw_gaussian\nend', file=inp_file)
            else:
                print('%cpcm\nsmd true\nSMDsolvent \"' + calc.solvent_keyword + '\"\nend', file=inp_file)

        if calc.optts_block:
            print(calc.optts_block, file=inp_file)
            if calc.core_atoms and calc.n_atoms > 25:
                core_atoms_str = ' '.join(map(str, calc.core_atoms))
                print(f'Hybrid_Hess [{core_atoms_str}] end', file=inp_file)
            print('end', file=inp_file)

        if calc.bond_ids_to_add:
            try:
                [print('%geom\nmodify_internal\n{ B', bond_ids[0], bond_ids[1], 'A } end\nend', file=inp_file)
                 for bond_ids in calc.bond_ids_to_add]
            except (IndexError, TypeError):
                logger.error('Could not add scanned bond')

        if calc.distance_constraints:
            print('%geom Constraints', file=inp_file)
            for bond_ids in calc.distance_constraints.keys():
                print('{ B', bond_ids[0], bond_ids[1], calc.distance_constraints[bond_ids], 'C }',
                      file=inp_file)
            print('    end\nend', file=inp_file)

        if calc.cartesian_constraints:
            print('%geom Constraints', file=inp_file)
            [print('{ C', atom_id, 'C }', file=inp_file)
             for atom_id in calc.cartesian_constraints]
            print('    end\nend', file=inp_file)

        if calc.n_atoms < 33:
            print('%geom MaxIter 100 end', file=inp_file)

        if calc.partial_hessian:
            print('%freq\nPartial_Hess {', file=inp_file, end='')
            print(*calc.partial_hessian, file=inp_file, end='')
            print('} end\nend', file=inp_file)

        if calc.charges is not None:
            print(f'% pointcharges "{calc.name}_orca.pc"', file=inp_file)

        if calc.n_cores > 1:
            print('%pal nprocs ' + str(calc.n_cores) + '\nend', file=inp_file)
        print('%output \nxyzfile=True \nend ', file=inp_file)
        print('%scf \nmaxiter 250 \nend', file=inp_file)
        print('% maxcore', calc.max_core_mb, file=inp_file)
        print('*xyz', calc.charge, calc.mult, file=inp_file)
        [print('{:<3} {:^12.8f} {:^12.8f} {:^12.8f}'.format(*line), file=inp_file) for line in calc.xyzs]
        print('*', file=inp_file)

    if calc.charges:
        with open(f'{calc.name}_orca.pc', 'w') as pc_file:
            print(len(calc.charges), file=pc_file)
            for line in calc.charges:
                formatted_line = [line[-1]] + line[1:4]
                print('{:^12.8f} {:^12.8f} {:^12.8f} {:^12.8f}'.format(*formatted_line), file=pc_file)
        calc.additional_input_files.append(f'{calc.name}_orca.pc')

    return None


def calculation_terminated_normally(calc):

    for n_line, line in enumerate(calc.rev_output_file_lines):
        if any(substring in line for substring in['ORCA TERMINATED NORMALLY', 'The optimization did not converge', 'HUGE, UNRELIABLE STEP WAS ABOUT TO BE TAKEN']):
            logger.info('ORCA terminated normally')
            return True
        if n_line > 30:
            # The above lines are pretty close to the end of the file – there's no point parsing it all
            return False


def get_energy(calc):
    for line in calc.rev_output_file_lines:
        if 'FINAL SINGLE POINT ENERGY' in line:
            return float(line.split()[4])


def optimisation_converged(calc):

    for line in calc.rev_output_file_lines:
        if 'THE OPTIMIZATION HAS CONVERGED' in line:
            return True

    return False


def optimisation_nearly_converged(calc):
    geom_conv_block = False

    for line in calc.rev_output_file_lines:
        if geom_conv_block and 'Geometry convergence' in line:
            geom_conv_block = False
        if 'The optimization has not yet converged' in line:
            geom_conv_block = True
        if geom_conv_block and len(line.split()) == 5:
            if line.split()[-1] == 'YES':
                return True
    return False


def get_imag_freqs(calc):
    imag_freqs = None

    if calc.partial_hessian:
        n_atoms = len(calc.partial_hessian)
    else:
        n_atoms = calc.n_atoms

    for i, line in enumerate(calc.output_file_lines):
        if 'VIBRATIONAL FREQUENCIES' in line:
            freq_lines = calc.output_file_lines[i + 5:i + 3 * n_atoms + 5]
            freqs = [float(l.split()[1]) for l in freq_lines]
            imag_freqs = [freq for freq in freqs if freq < 0]

    logger.info(f'Found imaginary freqs {imag_freqs}')
    return imag_freqs


def get_normal_mode_displacements(calc, mode_number):
    normal_mode_section, values_sec, displacements, col = False, False, [], None

    if calc.partial_hessian:
        n_atoms = len(calc.partial_hessian)
    else:
        n_atoms = calc.n_atoms

    for j, line in enumerate(calc.output_file_lines):
        if 'NORMAL MODES' in line:
            normal_mode_section, values_sec, displacements, col = True, False, [], None

        if 'IR SPECTRUM' in line:
            normal_mode_section, values_sec = False, False

        if normal_mode_section and len(line.split()) > 1:
            if line.split()[0].startswith('0'):
                values_sec = True

        if values_sec:
            if '.' not in line and len(line.split()) > 1:
                mode_numbers = [int(val) for val in line.split()]
                if mode_number in mode_numbers:
                    col = [i for i in range(len(mode_numbers)) if mode_number == mode_numbers[i]][0] + 1
                    displacements = [float(disp_line.split()[col]) for disp_line in
                                     calc.output_file_lines[j + 1:j + 3 * n_atoms + 1]]

    displacements_xyz = [displacements[i:i + 3]
                         for i in range(0, len(displacements), 3)]
    if len(displacements_xyz) != n_atoms:
        logger.error('Something went wrong getting the displacements n != n_atoms')
        return None

    return displacements_xyz


def get_final_xyzs(calc):

    xyzs = []
    if calc.output_filename:
        xyz_file_name = calc.output_filename[:-4] + '.xyz'
        if os.path.exists(xyz_file_name):
            with open(xyz_file_name, 'r') as file:
                for line_no, line in enumerate(file):
                    if line_no > 1:
                        atom_label, x, y, z = line.split()
                        xyzs.append([atom_label, float(x), float(y), float(z)])

    return xyzs


def get_atomic_charges(calc):

    charges_section = False
    charges = []
    for line in calc.output_file_lines:
        if 'MULLIKEN ATOMIC CHARGES' in line:
            charges_section = True
            charges = []
        if 'Sum of atomic charges' in line:
            charges_section = False
        if charges_section and len(line.split()) > 1:
            if line.split()[0].isdigit():
                if line.split()[1] != 'Q':
                    charges.append(float(line.split()[-1]))

    return charges


def get_gradients(calc):

    gradients_section = False
    gradients = []
    for line in calc.output_file_lines:
        if 'CARTESIAN GRADIENT' in line:
            gradients_section = True
        if 'Difference to translation invariance' in line:
            gradients_section = False
        if gradients_section and len(line.split()) == 6:
            atom, _, _, x, y, z = line.split()
            if atom != 'Q':
                gradients.append([float(x), float(y), float(z)])

    return gradients


# Bind all the required functions to the class definition
[setattr(ORCA, method, globals()[method]) for method in req_methods]
