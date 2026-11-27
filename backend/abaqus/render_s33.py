# -*- coding: utf-8 -*-
"""Executed with abaqus viewer noGUI, which owns Abaqus contour averaging."""
from __future__ import print_function

import json
from abaqus import session
from abaqusConstants import (COLOR, COMPONENT, CONTOURS_ON_UNDEF, INTEGRATION_POINT,
    OFF, ON, PNG)
import visualization

with open('s33-extracted.json', 'r') as source:
    raw = json.load(source)
odb = session.openOdb(name='clamp.odb', readOnly=True)
try:
    viewport = session.Viewport(name='S33', origin=(0, 0), width=180, height=120)
    viewport.setValues(displayedObject=odb)
    viewport.odbDisplay.setFrame(step=0, frame=raw['frame_index'])
    viewport.odbDisplay.basicOptions.setValues(averageElementOutput=ON, averagingThreshold=75.0)
    viewport.odbDisplay.setPrimaryVariable(variableLabel='S', outputPosition=INTEGRATION_POINT,
                                           refinement=(COMPONENT, 'S33'))
    viewport.odbDisplay.display.setValues(plotState=(CONTOURS_ON_UNDEF,))
    viewport.viewportAnnotationOptions.setValues(legend=ON, triad=ON, title=OFF)
    viewport.view.fitView()
    viewport.forceRefresh()
    extrema = viewport.getPrimVarMinMaxLoc()
    if not extrema or 'minValue' not in extrema or 'maxValue' not in extrema:
        raise RuntimeError('The Abaqus contour did not expose its S33 range.')
    low, high = float(extrema['minValue']), float(extrema['maxValue'])
    # Fix the printed legend to the same range that the result API returns.
    if low == high:
        delta = max(1e-9, abs(low) * 1e-8)
        legend_min, legend_max = low - delta, high + delta
    else:
        legend_min, legend_max = low, high
    viewport.odbDisplay.contourOptions.setValues(minAutoCompute=OFF, maxAutoCompute=OFF,
                                                 minValue=legend_min, maxValue=legend_max)
    session.printOptions.setValues(rendition=COLOR, vpDecorations=OFF)
    session.pngOptions.setValues(imageSize=(1600, 1050))
    session.printToFile(fileName='s33', format=PNG, canvasObjects=(viewport,))
    with open('result.json', 'w') as output:
        json.dump({
            'legend_min_mpa': legend_min, 'legend_max_mpa': legend_max,
            'peak_mpa': max(abs(low), abs(high)),
            'integration_point_min_mpa': raw['min_mpa'], 'integration_point_max_mpa': raw['max_mpa'],
            'odb_name': 'clamp.odb', 'averaging_threshold_percent': 75,
            'frame_index': raw['frame_index'],
        }, output, allow_nan=False)
finally:
    odb.close()
