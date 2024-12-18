# This is basically copied and pasted from /Users/tonyyan/Documents/_ANU/_He_BEC_Group/He34_Scattering/Rabi_Oscillations/Monitor_DLD_txy.ipynb
# Which is also on GitHub https://github.com/HeBECANU/He34_Scattering/blob/dev-tony/Rabi_Oscillations/Monitor_DLD_txy.py
import logging

# +
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from math import *
from uncertainties import *
from scipy.stats import chi2
from matplotlib import gridspec
import pandas
# import statsmodels.api as sm
import warnings  ## statsmodels.api is too old ... -_-#

import copy
import os
import re
from types import NoneType
import pylab
import scipy
import uncertainties.umath as um
from uncertainties import unumpy
from sys import getsizeof
import sys
import platform
import sysconfig


# -
# def is_notebook() -> bool:
#     # https://stackoverflow.com/questions/15411967/how-can-i-check-if-code-is-executed-in-the-ipython-notebook
#     try:
#         shell = get_ipython().__class__.__name__
#         if shell == 'ZMQInteractiveShell':
#             return True  # Jupyter notebook or qtconsole
#         elif shell == 'TerminalInteractiveShell':
#             return False  # Terminal running IPython
#         else:
#             return False  # Other type (?)
#     except NameError:
#         return False  # Probably standard Python interpreter


from dash import Dash, html, dash_table, dcc, callback, Output, Input
# from jupyter_dash import JupyterDash
from dash.dependencies import Input, Output
from plotly.subplots import make_subplots
import plotly.io as pio
import plotly.express as px
import plotly.graph_objects as go
import plotly.offline as pyo
import plotly

pl_detault_colors = plotly.colors.DEFAULT_PLOTLY_COLORS
# if is_notebook(): pio.renderers.default = 'iframe'

# +
# import git
#
# repo = git.Repo(search_parent_directories=True)
#
# # %config InlineBackend.figure_format = 'retina'
# # %matplotlib inline
# warnings.filterwarnings("ignore", category=DeprecationWarning)
# warnings.filterwarnings("ignore", category=FutureWarning)
# warnings.filterwarnings("ignore", category=UserWarning)
# plt.rcParams["figure.figsize"] = (8, 5)
# plt.rcParams["font.family"] = "serif"
# plt.rcParams["mathtext.fontset"] = "dejavuserif"
# plt.close("all")  # close all existing matplotlib plots
# # plt.ion()        # interact with plots without pausing program
#
#
# print(f"Python version {sys.version}\nPython Implementation : {platform.python_implementation()}")
# print(f"Node: {platform.node()}\
#         \nMachine: {platform.machine()}\
#         \nProcessor: {platform.processor()}\
#         \nSystem: {platform.system()}"
#       )
# print(f"Git Repo: {repo}\
#         \nBranch: {repo.active_branch}\
#         \nHead At: {repo.head.object.hexsha} at {repo.head.object.committed_datetime}")

# -

"""
Momentum State
"""


class State:
    def __init__(self, bound_lower, time_span, name_label):
        self.time_span = time_span
        self.bound_lower = bound_lower
        self.bound_upper = bound_lower + time_span
        self.name_label = name_label
        self.fig_label = name_label + " state"
        self.list_counts = []
        self.list_shotPo = []
        self.list_popAvg = []
        self.list_popStd = []
        popt = None
        pcov = None

    def __str__(self):
        return f"{self.name_label} state {self.bound_lower}-{self.bound_upper}"

    def fit_results(self):
        # print("ampt  =", str(round(self.popt[0], 5)), "±", str(round(self.pcov[0, 0] ** 0.5, 4)))
        # print("omega =", str(round(self.popt[1], 5)), "±", str(round(self.pcov[1, 1] ** 0.5, 4)))
        # print("damp  =", str(round(self.popt[2], 5)), "±", str(round(self.pcov[2, 2] ** 0.5, 4)))
        # print("vert  =", str(round(self.popt[3], 5)), "±", str(round(self.pcov[3, 3] ** 0.5, 4)))
        # print("phase =", str(round(self.popt[4], 5)), "±", str(round(self.pcov[4, 4] ** 0.5, 4)))
        logging.debug(f"""ampt  = {str(round(self.popt[0], 5))} ± {str(round(self.pcov[0, 0] ** 0.5, 4))}
omega = {str(round(self.popt[1], 5))} ± {str(round(self.pcov[1, 1] ** 0.5, 4))}
damp  = {str(round(self.popt[2], 5))} ± {str(round(self.pcov[2, 2] ** 0.5, 4))}
vert  = {str(round(self.popt[3], 5))} ± {str(round(self.pcov[3, 3] ** 0.5, 4))}
phase = {str(round(self.popt[4], 5))} ± {str(round(self.pcov[4, 4] ** 0.5, 4))}""")
        pass


# # Configurations

# +
# path_data_folder = '/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/SharePoint - He_ BEC-DFG Lab Jumbo Archives/temp working data/20230913_bragg_beams_k=0,-1_Pulse_length_scan_4'
path_data_folder_candadiate = [
    '/Volumes/tonyNVME Gold/dld output/20230913_bragg_beams_k=0,-1_Pulse_length_scan_3',
    'O:\\20230913_bragg_beams_k=0,-1_Pulse_length_scan_3',
    ]
path_data_folder = next((path for path in path_data_folder_candadiate if os.path.exists(path)), '')

path_log_Keysight = path_data_folder + "/log_KeysightMatlab.txt"

rangeTime = (1.85, 1.92)
nBins = 500

states = [State(1.865, 0.012, "-1"), State(1.881, 0.008, " 0"), State(1.893, 0.012, "+1")]

pio.renderers.default = 'iframe'
# pio.renderers.default = 'png'
# pio.renderers.default = 'vscode'


yes_my_computer_is_super_good_and_i_know_what_i_am_doing = True
# -


# +
logging.debug(f"scattering_proj_monitori_dld: Reading Data {path_data_folder}")
# print("Reading Data", path_data_folder)
# print("")
entries = os.listdir(path_data_folder)

with open(path_log_Keysight) as file:
    keysightLogs = [line.rstrip() for line in file]
# print("Found", len(keysightLogs), "keyightlogs")
logging.debug(f"scattering_proj_monitori_dld: Found {len(keysightLogs)} keyightlogs")

accum_ignored = 0
accum_found = 0
shotNo_exist = []
for e in entries:
    if e[:10] == 'd_txy_forc':
        num = int(e.split('.')[0][10:])
        accum_found += 1
        if num > len(keysightLogs):
            accum_ignored += 1
        else:
            shotNo_exist.append(num)
shotNo_exist.sort()

assert len(shotNo_exist) > 0, "No txy files?"
assert shotNo_exist[-1] == len(shotNo_exist), "Missing files?"
# assert accum_found==len(shotNo_exist), "They literally must equal"
numShots = len(shotNo_exist)
# print("Found", accum_found, "shots txy files, ignore", accum_ignored)
logging.debug(f"scattering_proj_monitori_dld: Found {accum_found} shots txy files, ignore {accum_ignored}")

data_np_loaded = {}

for e in shotNo_exist:
    this_data = np.loadtxt(path_data_folder + '/d_txy_forc' + str(e) + '.txt', delimiter=',')
    this_data = np.ndarray.flatten(this_data)
    this_data = np.reshape(this_data, (np.size(this_data) // 3, 3))
    # yes, i know, i know, there must be a better way, but i don't care anymore
    data_np_loaded[e] = this_data

# print(getsizeof(data_np_loaded) / 1000, "KB loaded")
# -

data_np_loaded_multi = None
for e in shotNo_exist:
    this_data = np.ndarray.flatten(data_np_loaded[e])
    if isinstance(data_np_loaded_multi, NoneType):
        data_np_loaded_multi = this_data
    else:
        data_np_loaded_multi = np.append(data_np_loaded_multi, this_data)
assert np.size(data_np_loaded_multi) % 3 == 0, "This data is fucked"
data_np_loaded_multi = np.reshape(data_np_loaded_multi, (np.size(data_np_loaded_multi) // 3, 3))

# +
counts, bins = np.histogram(data_np_loaded[1], bins=nBins, range=rangeTime)

data_compare_shots = np.array([])
data_compare_shots_density = np.array([])

data_compare_shots_x = np.array([])
data_compare_shots_y = np.array([])

for e in shotNo_exist:
    this_data = data_np_loaded[e][:, 0]
    this_data_x = data_np_loaded[e][:, 1]
    this_data_y = data_np_loaded[e][:, 2]
    thisCounts, _ = np.histogram(this_data, bins=nBins, range=rangeTime)
    thisCounts_x, _ = np.histogram(this_data_x, bins=nBins, range=(-0.03, +0.03))
    thisCounts_y, _ = np.histogram(this_data_y, bins=nBins, range=(-0.03, +0.03))
    data_compare_shots = np.append(data_compare_shots, thisCounts)
    data_compare_shots_x = np.append(data_compare_shots_x, thisCounts_x)
    data_compare_shots_y = np.append(data_compare_shots_y, thisCounts_y)

data_compare_shots = np.reshape(data_compare_shots, (numShots, nBins))
data_compare_shots_x = np.reshape(data_compare_shots_x, (numShots, nBins))
data_compare_shots_y = np.reshape(data_compare_shots_y, (numShots, nBins))
# data_compare_shots_density = np.reshape(data_compare_shots_density, (numShots,numBins))
# print(getsizeof(data_compare_shots)/1000, "KB")

# +
fucked_shot = np.full(len(shotNo_exist), False)
ind_pulseDuration = np.full(len(shotNo_exist), -1.0)
set_pulseDuration = set()

for state in states: state.list_counts = []
for state in states: state.list_shotPo = []

for i in range(len(shotNo_exist)):
    e = shotNo_exist[i]
    log_shotNo = int(keysightLogs[i].split(',')[0].split(":")[1])
    log_pulseDuration = float(keysightLogs[i].split(',')[14])
    assert e == log_shotNo, f"This data/log is fucked up at i={i}, e={e},logNo={log_shotNo}"

    ind_pulseDuration[i] = log_pulseDuration
    set_pulseDuration.add(log_pulseDuration)

    this_data = data_np_loaded[e]
    this_data_t = this_data[:, 0]
    this_data_x = this_data[:, 1]
    this_data_y = this_data[:, 2]

    normlisation = 0
    for state in states:
        counts = np.sum(np.logical_and(this_data_t > state.bound_lower, this_data_t < state.bound_upper))
        state.list_counts.append(counts)
        normlisation += counts
    total_counts = len(this_data_t)
    if normlisation == 0:
        fucked_shot[i] = True
        for state in states:
            state.list_shotPo.append(nan)
    else:
        for state in states:
            state.list_shotPo.append(state.list_counts[-1] / normlisation)
np_pulseDurations = np.sort(list(set_pulseDuration))
# print("very fucked shots", np.sum(fucked_shot))
# -
# np_pulseDurations

# np.array(list_pulseDuration)

# np_pulseDurations == np.array(list_pulseDuration)

# np.array_equal(list_pulseDuration, np_pulseDurations)

# +
list_pulseDuration = []

for state in states:  state.list_popAvg = []
for state in states:  state.list_popStd = []

for pd in np_pulseDurations:
    relaventShots = ind_pulseDuration == pd
    list_pulseDuration.append(pd)
    for state in states:
        state.list_popAvg.append(np.nanmean(state.list_shotPo, where=relaventShots))
        state.list_popStd.append(np.nanstd(state.list_shotPo, where=relaventShots))


# +
def fit_function(t, ampt, omega, damp, vert, phase):
    return ampt * np.exp(-damp * t) * np.cos(omega * t + phase) + vert


def fit_function_u(t, ampt, omega, damp, vert, phase):
    return ampt * um.exp(-damp * t) * um.cos(omega * t + phase) + vert


freq_list = []
for state in states:
    try:
        state.popt, state.pcov = scipy.optimize.curve_fit(
            f=fit_function,
            xdata=np.array(list_pulseDuration) * 1e6,
            ydata=state.list_popAvg,
            p0=[0.5, 0.08, 0.05, 0.5, 0],
            sigma=state.list_popStd
        )
        # print("fit results", state.fig_label)
        state.fit_results()
        freq_list.append(ufloat(state.popt[0], state.pcov[1, 1]))
    except:
        pass
        # print("fit failed for", state.fig_label)
    # print("")


tlin = np.linspace(0, list_pulseDuration[-1] * 1e6, 1000)
cs = plt.rcParams['axes.prop_cycle'].by_key()['color']

rabi_measured = np.mean(freq_list)
# print("ω measured = ", rabi_measured, "/μs")
# print("Period =", 2 * np.pi / rabi_measured, "μs")
# -


# # Change plots to plotly style


# +
temp_plot_filter_t = data_np_loaded_multi[:, 0]
temp_plot_filter_t = temp_plot_filter_t[(temp_plot_filter_t >= rangeTime[0]) * (temp_plot_filter_t <= rangeTime[1])]

temp_plot_filter_x = data_np_loaded_multi[:, 1] * 1e3
temp_plot_filter_y = data_np_loaded_multi[:, 2] * 1e3

fig = make_subplots(rows=3, cols=1, vertical_spacing=0.05)

fig.append_trace(go.Histogram(x=temp_plot_filter_t, nbinsx=nBins, name="time (s)"), row=1, col=1)
fig.append_trace(go.Histogram(x=temp_plot_filter_x, nbinsx=nBins, name="x(mm)"), row=2, col=1)
fig.append_trace(go.Histogram(x=temp_plot_filter_y, nbinsx=nBins, name="y(mm)"), row=3, col=1)

fig.update_layout(
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0
    ),
    autosize=True,
    # width=900,
    # height=500,
    margin=dict(l=0, r=0, t=0, b=0),
)

fig_txt_density = copy.deepcopy(fig)
# fig.show()
# fig.show(renderer="png")

# +
fig = go.Figure(data=[
    go.Scatter3d(
        x=data_np_loaded_multi[:, 1] * 1e3, y=data_np_loaded_multi[:, 2] * 1e3, z=data_np_loaded_multi[:, 0],
        mode='markers',
        marker=dict(size=1, opacity=0.1)
    )
])
fig.update_layout(
    scene=dict(
        xaxis=dict(nticks=4, range=[-30, 30], ),
        yaxis=dict(nticks=4, range=[-30, 30], ),
        zaxis=dict(nticks=4, range=[rangeTime[0] + 0.03, rangeTime[1] - 0.015])
        , ),
    width=800,
    margin=dict(r=0, l=0, b=0, t=0)
)
fig.update_layout(
    scene_aspectmode='manual',
    scene_aspectratio=dict(x=1, y=1, z=1)
)
fig.update_layout(
    scene=dict(
        xaxis_title='x (mm)',
        yaxis_title='y (mm)',
        zaxis_title='time (s)'
    )
)

fig_txy_3d = copy.deepcopy(fig)
# fig.show()
# fig.show(renderer="jpeg")
# -

test_t_lin = np.linspace(rangeTime[0], rangeTime[1], nBins)
test_x_lin = np.linspace(-30, +30, nBins)

# +
fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.0,
    x_title="Shot No.",
    row_heights=[0.5, 0.25, 0.25],
)
fig.add_trace(go.Heatmap(
    z=data_compare_shots.T,
    colorscale="Blues",
    showscale=False,
    y=test_t_lin,
), row=1, col=1)
fig.add_trace(go.Heatmap(
    z=data_compare_shots_x.T,
    colorscale="Blues",
    showscale=False,
    y=test_x_lin,
), row=2, col=1)
fig.add_trace(go.Heatmap(
    z=data_compare_shots_y.T,
    colorscale="Blues",
    showscale=False,
    y=test_x_lin,
), row=3, col=1)

for state in states:
    fig.add_shape(
        type="rect", row=1, col=1,
        x0=0, y0=state.bound_lower, x1=numShots, y1=state.bound_upper,
        line=dict(color="RoyalBlue", width=0, ),
        fillcolor="Red",
        opacity=0.08
    )
    fig.add_annotation(
        x=numShots * 0.95, y=state.bound_upper + 0.0016,
        text=state.fig_label,
        showarrow=False,
        font=dict(color="Red")
    )

fig.update_layout(showlegend=False)
# fig.update_traces(colorbar=None)
# fig.update_traces(marker_showscale=False)
# fig.update_layout(coloraxis_showscale=False)
# fig.update_traces(marker_coloraxis=None)

fig.update_xaxes(showline=True, linewidth=1, linecolor='gray', mirror=True)
fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)

fig.update_layout(
    yaxis1=dict(title="time (s)"),
    yaxis2=dict(title="x (mm)"),
    yaxis3=dict(title="y (mm)"),
)
fig.update_layout(
    autosize=True,
    # width=800,
    # height=700,
    margin=dict(l=0, r=0, t=20, b=50),
)

fig_shots_scan = copy.deepcopy(fig)
# fig.show()
# fig.show(renderer="png")


# +
fig = go.Figure()

for state in states:
    fig.add_scatter(
        x=shotNo_exist,
        y=state.list_shotPo,
        mode="markers+lines",
        opacity=0.8,
        name=state.fig_label
    )
fig.update_layout(
    xaxis=dict(title="Shot No."),
    yaxis=dict(title="Proportion"),
    legend=dict(
        yanchor="top",
        y=0.99,
        xanchor="right",
        x=0.99,
        orientation="h"
    ),
    autosize=True,
    # width=900,
    # height=500,
    margin=dict(l=0, r=0, t=0, b=0),
)

fig_shots_transfer = copy.deepcopy(fig)
# fig.show()

# + active=""
# fig = go.Figure()
#
# for state in states:
#     fig.add_scatter(
#         x = np.array(list_pulseDuration)*1e6,
#         y = state.list_popAvg,
#         mode = "markers+lines",
#         opacity = 0.7,
#         name = state.fig_label,
#         error_y=dict(
#             type = 'data',
#             array = state.list_popStd,
#             visible = True,
#             width = 2.5,
#         ),
#         marker = dict(
#             size=12
#         )
#     )
# fig.update_layout(
#     xaxis = dict(title = "Gaussian Pulse Width μs"),
#     yaxis = dict(title = "Proportion"),
#     legend=dict(
#         yanchor = "top",
#         y = 0.99,
#         xanchor = "right",
#         x = 0.99,
#         orientation = "h"
#     ),
#     autosize = False,
#     width  = 900,
#     height = 500,
#     margin = dict(l=0, r=0, t=0, b=0),
# )
#
# fig_pulse_eff = copy.deepcopy(fig)
# # fig.show()

# +
fig = go.Figure()

for (i, state) in enumerate(states):
    cc = pl_detault_colors[i]
    fig.add_scatter(
        x=np.array(list_pulseDuration) * 1e6,
        y=state.list_popAvg,
        mode="markers+lines",
        opacity=0.7,
        name=state.fig_label,
        error_y=dict(
            type='data',
            array=state.list_popStd,
            visible=True,
            width=2.5,
        ),
        marker=dict(
            size=12,
            color=cc
        ),
    )

    try:
        popt = state.popt
        pcov = state.pcov
        fit_linU = np.array([fit_function_u(t,
                                            ufloat(popt[0], pcov[0, 0] ** 0.5),
                                            ufloat(popt[1], pcov[1, 1] ** 0.5),
                                            ufloat(popt[2], pcov[2, 2] ** 0.5),
                                            ufloat(popt[3], pcov[3, 3] ** 0.5),
                                            ufloat(popt[4], pcov[4, 4] ** 0.5))
                             for t in tlin])
        fit_linMag = np.array([x.nominal_value for x in fit_linU])
        fit_linStd = np.array([x.std_dev for x in fit_linU])
        fig.add_trace(go.Scatter(
            x=tlin,
            y=fit_linMag + 2 * fit_linStd,
            mode="lines",
            line_color=cc,
            line=dict(width=0),
            showlegend=False
        ))
        fig.add_trace(go.Scatter(
            x=tlin,
            y=fit_linMag - 2 * fit_linStd,
            fill='tonexty',
            mode="lines",
            line_color=cc,
            line=dict(width=0),
            fillcolor=f"rgba{cc[3:-1]}, {0.2})",
            name="±2σ",
        ))

    except:
        continue

fig.update_layout(
    xaxis=dict(title="Gaussian Pulse Width μs"),
    yaxis=dict(title="Proportion"),
    legend=dict(
        yanchor="top",
        y=0.99,
        xanchor="right",
        x=0.99,
        orientation="h"
    ),
    autosize=True,
    # width=900,
    # height=500,
    margin=dict(l=0, r=0, t=0, b=0),
)
fig.update_layout(
    plot_bgcolor='white'
)
fig.update_xaxes(
    mirror=True,
    ticks='outside',
    showline=True,
    linecolor='black',
    # gridcolor='lightgrey'
)
fig.update_yaxes(
    mirror=True,
    ticks='outside',
    showline=True,
    linecolor='black',
    # gridcolor='lightgrey'
)

fig_pulse_eff_fitted = copy.deepcopy(fig)


# fig.show()
# -


# fig.show()
# -


# def fig_txt_density(path: str):
#     # +
#     temp_plot_filter_t = data_np_loaded_multi[:, 0]
#     temp_plot_filter_t = temp_plot_filter_t[(temp_plot_filter_t >= rangeTime[0]) * (temp_plot_filter_t <= rangeTime[1])]
#
#     temp_plot_filter_x = data_np_loaded_multi[:, 1] * 1e3
#     temp_plot_filter_y = data_np_loaded_multi[:, 2] * 1e3
#
#     fig = make_subplots(rows=3, cols=1, vertical_spacing=0.05)
#
#     fig.append_trace(go.Histogram(x=temp_plot_filter_t, nbinsx=nBins, name="time (s)"), row=1, col=1)
#     fig.append_trace(go.Histogram(x=temp_plot_filter_x, nbinsx=nBins, name="x(mm)"), row=2, col=1)
#     fig.append_trace(go.Histogram(x=temp_plot_filter_y, nbinsx=nBins, name="y(mm)"), row=3, col=1)
#
#     fig.update_layout(
#         legend=dict(
#             orientation="h",
#             yanchor="bottom",
#             y=1.02,
#             xanchor="left",
#             x=0
#         ),
#         autosize=True,
#         # width=900,
#         # height=500,
#         margin=dict(l=0, r=0, t=0, b=0),
#     )
#
#     fig_txt_density = copy.deepcopy(fig)
#     # fig.show()
#     # fig.show(renderer="png")
#
#
#
#     return fig_txt_density
#
#
#
#
# def fig_txy_3d(path: str):
#     fig = go.Figure(data=[
#         go.Scatter3d(
#             x=data_np_loaded_multi[:, 1] * 1e3, y=data_np_loaded_multi[:, 2] * 1e3, z=data_np_loaded_multi[:, 0],
#             mode='markers',
#             marker=dict(size=1, opacity=0.1)
#         )
#     ])
#     fig.update_layout(
#         scene=dict(
#             xaxis=dict(nticks=4, range=[-30, 30], ),
#             yaxis=dict(nticks=4, range=[-30, 30], ),
#             zaxis=dict(nticks=4, range=[rangeTime[0] + 0.03, rangeTime[1] - 0.015])
#             , ),
#         width=800,
#         margin=dict(r=0, l=0, b=0, t=0)
#     )
#     fig.update_layout(
#         scene_aspectmode='manual',
#         scene_aspectratio=dict(x=1, y=1, z=1)
#     )
#     fig.update_layout(
#         scene=dict(
#             xaxis_title='x (mm)',
#             yaxis_title='y (mm)',
#             zaxis_title='time (s)'
#         )
#     )
#
#     fig_txy_3d = copy.deepcopy(fig)
#
#     return fig_txy_3d