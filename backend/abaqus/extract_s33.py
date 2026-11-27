# -*- coding: utf-8 -*-
"""Executed with abaqus python; extract signed integration-point extrema."""
from __future__ import print_function

import json
from abaqusConstants import INTEGRATION_POINT
from odbAccess import openOdb

odb = openOdb(path='clamp.odb', readOnly=True)
try:
    frame = odb.steps['LOAD'].frames[-1]
    if frame.frameValue < 0.999999:
        raise RuntimeError('The last ODB frame does not reach the full analysis load.')
    field = frame.fieldOutputs['S'].getSubset(position=INTEGRATION_POINT)
    scalar = field.getScalarField(componentLabel='S33')
    low, high = float('inf'), -float('inf')
    for value in scalar.values:
        try:
            data = value.data
        except Exception:
            data = value.dataDouble
        number = float(data if isinstance(data, (int, float)) else data[0])
        low, high = min(low, number), max(high, number)
    if low > high:
        raise RuntimeError('No S33 integration point values were found.')
    with open('s33-extracted.json', 'w') as target:
        json.dump({'min_mpa': low, 'max_mpa': high, 'frame_index': len(odb.steps['LOAD'].frames)-1,
                   'frame_value': frame.frameValue}, target, allow_nan=False)
finally:
    odb.close()
