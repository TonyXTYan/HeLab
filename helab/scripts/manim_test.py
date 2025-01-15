from manim import *
import numpy as np
# from manimlib import VGroup, DEGREES, ThreeDAxes, ThreeDScene, WHITE


class Scatter3DScene(ThreeDScene):
    def construct(self):
        # Define axis bounds (same as Plotly ranges)
        x_min, x_max = -0.03, 0.03
        y_min, y_max = -0.03, 0.03
        z_min, z_max = 3.8, 3.9

        # Create 3D axes with the defined ranges
        axes = ThreeDAxes(
            x_range=[x_min, x_max, (x_max-x_min)/10],
            y_range=[y_min, y_max, (y_max-y_min)/10],
            z_range=[z_min, z_max, (z_max-z_min)/10],
            x_length=6, y_length=6, z_length=6
        )

        # Set an initial camera orientation for a good view of the 3D scene
        self.set_camera_orientation(phi=75 * DEGREES, theta=-45 * DEGREES)
        self.add(axes)

        # --- Data Loading and Processing ---
        # Replace this dummy data with your actual data loading logic
        # For example, using your custom data loader:
        # data = LoadFolderToRamWorker.default_algorithm_decompress(...)
        # Process the data to form all_points as in your Plotly example.

        # For demonstration purposes, we'll create random points:
        # all_points is expected to be an array of shape (N, 3): [t, x, y]
        num_points = 200  # For visualization; adjust as needed
        all_points = np.column_stack((
            np.random.uniform(z_min, z_max, num_points),
            np.random.uniform(x_min, x_max, num_points),
            np.random.uniform(y_min, y_max, num_points)
        ))

        # Create a VGroup to hold all 3D dots
        dots = VGroup()
        for point in all_points:
            # point format: [t, x, y] => map to (x, y, z) for 3D plot where z = t
            x_coord = point[1]
            y_coord = point[2]
            z_coord = point[0]

            # Convert data point to the scene's coordinate system
            point_in_scene = axes.c2p(x_coord, y_coord, z_coord)

            # Create a 3D dot at this position
            dot = Dot3D(point=point_in_scene, radius=0.02, color=WHITE)
            dots.add(dot)

        # Add all dots to the scene
        self.add(dots)

        # Optionally, animate the camera to rotate around the scene
        self.begin_ambient_camera_rotation(rate=0.1)  # Slow continuous rotation

        # Hold the final frame for a short duration
        self.wait(5)
