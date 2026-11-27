# -*- coding: utf-8 -*-
"""Abaqus/CAE noGUI entry point; also importable for input-deck verification."""
from __future__ import print_function

import bisect
import json
import math
import os


def divisions(stations, target):
    unique = []
    for value in sorted(stations):
        if not unique or value - unique[-1] > 1e-7:
            unique.append(value)
    coordinates = [unique[0]]
    for low, high in zip(unique[:-1], unique[1:]):
        count = max(1, int(math.ceil((high - low) / target)))
        coordinates.extend(low + (high - low) * i / count for i in range(1, count))
        coordinates.append(high)
    return coordinates


def node_index(axis, coordinate):
    i = bisect.bisect_left(axis, coordinate)
    candidates = [k for k in (i - 1, i) if 0 <= k < len(axis)]
    nearest = min(candidates, key=lambda k: abs(axis[k] - coordinate))
    if abs(axis[nearest] - coordinate) > 1e-6:
        raise ValueError("Bolt coordinate is absent from the structured mesh.")
    return nearest


MESH_LIMIT = 160000


def model_axes(params):
    cavity_x, cavity_y = params['L'] / 2.0, params['W'] / 2.0
    outer_x = cavity_x + params['off'] + params['flange_lip_mm']
    outer_y = cavity_y + params['off'] + params['flange_lip_mm']
    plate_x, plate_y = outer_x + params['plate_edge_mm'], outer_y + params['plate_edge_mm']
    holes, mesh_size = params['holes'], params['mesh_mm']
    x = divisions([-plate_x, -outer_x, -cavity_x, cavity_x, outer_x, plate_x] +
                  [h['x_mm'] for h in holes], mesh_size)
    y = divisions([-plate_y, -outer_y, -cavity_y, cavity_y, outer_y, plate_y] +
                  [h['y_mm'] for h in holes], mesh_size)
    t, flange_t = params['plate_thickness_mm'], params['flange_thickness_mm']
    z = divisions([0.0, t, t + flange_t], mesh_size)
    return x, y, z, node_index(z, t), (cavity_x, cavity_y), (outer_x, outer_y)


def mesh_preflight(params):
    x, y, z, interface, cavity, outer = model_axes(params)
    nx, ny, nz = len(x) - 1, len(y) - 1, len(z) - 1

    def bands(axis, inner, outer):
        midpoints = [abs((a + b) / 2.0) for a, b in zip(axis, axis[1:])]
        return sum(p < inner for p in midpoints), sum(p < outer for p in midpoints)

    wet_x, flange_x = bands(x, cavity[0], outer[0])
    wet_y, flange_y = bands(y, cavity[1], outer[1])
    pressure_faces = wet_x * wet_y
    return {
        "elements": nx * ny * interface + (flange_x * flange_y - pressure_faces) * (nz - interface),
        "pressure_faces": pressure_faces,
        "thrust_kn": params['pressure_mpa'] * params['L'] * params['W'] / 1000.0,
        "within_mesh_limit": nx * ny * nz <= MESH_LIMIT,
        "mesh_limit": MESH_LIMIT,
    }


def write_deck(params, destination):
    """C3D8 mesh with matching nodes across a perfectly bonded flange interface."""
    x, y, z, interface, (cavity_x, cavity_y), (outer_x, outer_y) = model_axes(params)
    nx, ny, nz = len(x) - 1, len(y) - 1, len(z) - 1
    if nx * ny * nz > MESH_LIMIT:
        raise ValueError("Estimated mesh exceeds %d cells; increase mesh size or reduce bolt count." % MESH_LIMIT)
    holes = params['holes']
    labels, nodes, concrete, flange, water_elements = {}, [], [], [], []

    def node(i, j, k):
        location = (i, j, k)
        if location not in labels:
            labels[location] = len(nodes) + 1
            nodes.append((labels[location], x[i], y[j], z[k]))
        return labels[location]

    element = 0
    for i in range(nx):
        mx = (x[i] + x[i+1]) / 2
        for j in range(ny):
            my = (y[j] + y[j+1]) / 2
            cavity = abs(mx) < cavity_x and abs(my) < cavity_y
            in_flange = abs(mx) < outer_x and abs(my) < outer_y and not cavity
            for k in range(nz if in_flange else interface):
                element += 1
                connectivity = (
                    node(i,j,k), node(i+1,j,k), node(i+1,j+1,k), node(i,j+1,k),
                    node(i,j,k+1), node(i+1,j,k+1), node(i+1,j+1,k+1), node(i,j+1,k+1),
                )
                (concrete if k < interface else flange).append((element,) + connectivity)
                if cavity and k == interface - 1:
                    water_elements.append(element)
    if not concrete or not flange or not water_elements:
        raise ValueError("Model is missing concrete, flange or water pressure faces.")

    base = [label for (i,j,k),label in labels.items() if k == 0]
    loaded = []
    for hole in holes:
        key = (node_index(x, hole['x_mm']), node_index(y, hole['y_mm']), nz)
        if key not in labels:
            raise ValueError("A bolt lies outside the flange mesh.")
        loaded.append(labels[key])

    def set_values(out, header, values):
        out.write(header + '\n')
        for i in range(0, len(values), 12):
            out.write(', '.join(str(v) for v in values[i:i+12]) + '\n')

    with open(destination, 'w') as out:
        out.write('*HEADING\nRectangular flange on bonded concrete plate, N-mm-MPa\n*NODE\n')
        for label, px, py, pz in nodes:
            out.write('%d, %.12g, %.12g, %.12g\n' % (label, px, py, pz))
        for name, elements in (('CONCRETE', concrete), ('FLANGE', flange)):
            out.write('*ELEMENT, TYPE=C3D8, ELSET=%s\n' % name)
            for entry in elements:
                out.write(', '.join(map(str, entry)) + '\n')
        set_values(out, '*NSET, NSET=FIXED_BASE', base)
        set_values(out, '*ELSET, ELSET=WATER_TOP', water_elements)
        out.write('*SURFACE, TYPE=ELEMENT, NAME=WATER_PRESSURE\nWATER_TOP, S2\n')
        for name, modulus, poisson in (
            ('CONCRETE', params['concrete_e_mpa'], params['concrete_nu']),
            ('FLANGE', params['flange_e_mpa'], params['flange_nu']),
        ):
            out.write('*MATERIAL, NAME=%s\n*ELASTIC\n%.12g, %.12g\n' % (name, modulus, poisson))
            out.write('*SOLID SECTION, ELSET=%s, MATERIAL=%s\n,\n' % (name, name))
        out.write('*BOUNDARY\nFIXED_BASE, 1, 3, 0.\n')
        out.write('*STEP, NAME=LOAD, NLGEOM=NO, INC=100\n*STATIC\n0.1, 1., 1.e-6, 0.2\n')
        out.write('*DSLOAD\nWATER_PRESSURE, P, %.12g\n' % params['pressure_mpa'])
        out.write('*CLOAD\n')
        for label in loaded:
            out.write('%d, 3, %.12g\n' % (label, -1000.0 * params['force_kn']))
        out.write('*OUTPUT, FIELD, FREQUENCY=1\n*ELEMENT OUTPUT\nS\n*NODE OUTPUT\nU\n*END STEP\n')
    return {"nodes": len(nodes), "elements": element, "pressure_faces": len(water_elements),
            "bolt_load_nodes": len(loaded), "flange_elements": len(flange)}


def main():
    from abaqus import mdb
    from abaqusConstants import COMPLETED, OFF
    with open('input.json', 'r') as source:
        envelope = json.load(source)
    mesh = write_deck(envelope['parameters'], 'model.inp')
    with open('mesh.json', 'w') as out:
        json.dump(mesh, out)
    os.mkdir('scratch')
    job = mdb.JobFromInputFile(name='clamp', inputFileName='model.inp',
        numCpus=envelope['cpus'], scratch=os.path.abspath('scratch'))
    job.submit(consistencyChecking=OFF)
    job.waitForCompletion()
    if job.status != COMPLETED or not os.path.isfile('clamp.odb'):
        raise RuntimeError('Abaqus/Standard did not complete: %s' % job.status)


if __name__ == '__main__':
    main()
