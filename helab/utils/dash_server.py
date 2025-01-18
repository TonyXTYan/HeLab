import threading
from typing import Optional, Dict, Any

import dash
from dash import html, Output, Input, dcc
from dash.html import Figure

from helab.utils.synchronised_dict import SynchronisedDict


class DashServer:
    def __init__(self) -> None:
        self.app = dash.Dash(__name__, suppress_callback_exceptions=True)
        self.plots: SynchronisedDict[str, Figure] = SynchronisedDict()
        self.setup_layout()
        threading.Thread(target=self.run_server, daemon=True).start()

    def setup_layout(self) -> None:
        self.app.layout = html.Div([
            dcc.Location(id='url', refresh=False),
            html.Div(id='page-content')
        ])

        @self.app.callback(Output('page-content', 'children'),  # type: ignore
                           Input('url', 'pathname'))
        def display_page(pathname: Optional[str]) -> Any:
            print(f"{pathname = }")
            if pathname and pathname.startswith('/plot/'):
                plot_id = pathname.split('/plot/')[1]
                fig = self.plots.get(plot_id)
                if fig:
                    return dcc.Graph(figure=fig)
            return html.Div("Plot not found.")

    def add_plot(self, plot_id: str, fig: Figure) -> None:
        self.plots[plot_id] = fig

    def run_server(self) -> None:
        # self.app.run_server(host="192.168.1.23", port=8050, debug=False, use_reloader=False)
        self.app.run_server(host="127.0.0.1", port=8050, debug=False, use_reloader=False)