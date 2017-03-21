import logging
import itertools

import cv2
import matplotlib.pyplot as plt
import matplotlib
# import cmocean
import scipy.interpolate
import numpy as np
import skimage.draw
import sys

from .cm import terrajet2
from .sandbox_fm import compute_delta_zk
import sandbox_fm.models

from .calibrate import (
    transform,
    HEIGHT,
    WIDTH
)

matplotlib.rcParams['toolbar'] = 'None'

logger = logging.getLogger(__name__)


def warp_flow(img, flow):
    """transform image with flow field"""
    h, w = flow.shape[:2]
    flow = -flow
    flow[:, :, 0] += np.arange(w)
    flow[:, :, 1] += np.arange(h)[:, np.newaxis]
    res = cv2.remap(img, flow, None, cv2.INTER_LINEAR,
                    borderValue=(1.0, 1.0, 1.0, 0.0))
    return res


def process_events(evt, data, model, vis):
    """handle keystrokes and other interactions"""
    meta = getattr(sandbox_fm.models, model.engine)

    if not isinstance(evt, matplotlib.backend_bases.KeyEvent):
        return
    if evt.key == 'b':  # Set bed level to current camera bed level
        # data['bl'][idx] += compute_delta_bl(data, idx)
        idx = np.logical_and(data['node_in_box'], data['node_in_img_bbox'])
        zk_copy = data['zk'].copy()
        zk_copy[idx] += compute_delta_zk(data, idx)
        # replace the part that changed
        print(np.where(idx))
        for i in np.where(idx)[0]:
            if data['zk'][i] != zk_copy[i]:
                # TODO: bug in zk
                model.set_var_slice('zk', [i + 1], [1], zk_copy[i:i + 1])
    if evt.key == 'r':  # Reset to original bed level
        for i in range(0, len(data['depth_cells_original'])):
            if data['DEPTH_CELLS'][i] != data['depth_cells_original'][i]:
                model.set_var_slice(mappings["DEPTH_CELLS"], [i + 1], [1],
                                    data['depth_cells_original'][i:i + 1])
    if evt.key == 'p':
        vis.lic[:, :, :3] = 1.0
        vis.lic[:, :, 3] = 0.0
        vis.lic = cv2.warpPerspective(
            data['video'].astype('float32') / 255.0,
            np.array(data['img2box']),
            data['height'].shape[::-1]
        )
        if vis.lic.shape[-1] == 3:
            # add depth channel
            vis.lic = np.dstack([
                vis.lic,
                np.ones_like(vis.lic[:, :, 0])
            ])

    if evt.key == 'c':
        vis.im_flow.set_visible(not vis.im_flow.get_visible())
    if evt.key == 'q':  # Quit (on windows)
        sys.exit()
    if evt.key == '1':  # Visualisation preset 1. Show bed level from camera
        vis.im_waterlevel.set_visible(False)
        vis.im_height.set_visible(True)
        vis.im_zk.set_visible(False)
        vis.im_mag.set_visible(False)
    if evt.key == '2':  # Visualisation preset 2. Show water level in model
        vis.im_waterlevel.set_visible(True)
        vis.im_height.set_visible(False)
        vis.im_zk.set_visible(False)
        vis.im_mag.set_visible(False)
    if evt.key == '3':  # Visualisation preset 3. Show bed level in model
        vis.im_waterlevel.set_visible(False)
        vis.im_height.set_visible(False)
        vis.im_zk.set_visible(True)
        vis.im_mag.set_visible(False)
    if evt.key == '4':  # Visualisation preset . Show flow magnitude in model
        vis.im_waterlevel.set_visible(False)
        vis.im_height.set_visible(False)
        vis.im_zk.set_visible(False)
        vis.im_mag.set_visible(True)


class Visualization():
    def __init__(self):
        # create figure and axes
        self.fig, self.ax = plt.subplots()
        self.fig.subplots_adjust(
            left=0,
            right=1,
            bottom=0,
            top=1
        )
        self.ax.axis('off')
        plt.ion()
        plt.show(block=False)
        self.lic = None
        self.background = None
        self.counter = itertools.count()
        self.subscribers = []

    def notify(self, event):
        for subscriber in self.subscribers:
            subscriber(event)

    def initialize(self, data):
        # create plots here (not sure why shape is reversed)
        warped_height = cv2.warpPerspective(
            data['height'].filled(0),
            np.array(data['img2box']),
            data['height'].shape[::-1]
        )

        # rgba image
        self.lic = cv2.warpPerspective(
            np.zeros_like(data['video']).astype('float32'),
            np.array(data['img2box']),
            data['height'].shape[::-1]
        )

        if self.lic.shape[-1] == 3:
            # add depth channel
            self.lic = np.dstack([self.lic, np.zeros_like(self.lic[:, :, 0])])

        # transparent, white background
        if data['background'].exists():
            self.background = plt.imread(str(data['background']))

        # get the xlim from the height image
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        # row, column indices
        v, u = np.mgrid[:HEIGHT, :WIDTH]

        # xy of model in image coordinates
        x_cell_box, y_cell_box = transform(
            data['X_CELLS'].ravel(),
            data['Y_CELLS'].ravel(),
            data['model2box']
        )
        # transform vectors
        x_cell_u_box, y_cell_v_box = transform(
            (data['X_CELLS'] + data['U']).ravel(),
            (data['Y_CELLS'] + data['V']).ravel(),
            data['model2box']
        )
        u_in_img = x_cell_box - x_cell_u_box
        v_in_img = y_cell_box - y_cell_v_box

        u_t, v_t = transform(
            u.ravel().astype('float32'),
            v.ravel().astype('float32'),
            data['box2model']
        )
        tree = scipy.spatial.cKDTree(np.c_[data['X_CELLS'].ravel(), data['Y_CELLS'].ravel()])
        distances_cells, ravensburger_cells = tree.query(np.c_[u_t, v_t])
        print("shapes", distances_cells.shape, ravensburger_cells.shape)
        data['ravensburger_cells'] = ravensburger_cells.reshape(HEIGHT, WIDTH)
        data['distances_cells'] = distances_cells.reshape(HEIGHT, WIDTH)
        tree = scipy.spatial.cKDTree(np.c_[data['X_NODES'].ravel(), data['Y_NODES'].ravel()])
        distances_nodes, ravensburger_nodes = tree.query(np.c_[u_t, v_t])
        data['ravensburger_nodes'] = ravensburger_nodes.reshape(HEIGHT, WIDTH)
        data['distances_nodes'] = distances_nodes.reshape(HEIGHT, WIDTH)

        data['node_mask'] = data['distances_nodes'] > 500
        data['cell_mask'] = data['distances_cells'] > 500

        waterlevel_img = data['WATERLEVEL'].ravel()[data['ravensburger_cells']]
        u_img = u_in_img[data['ravensburger_cells']]
        v_img = v_in_img[data['ravensburger_cells']]
        depth_cells_img = data['DEPTH_CELLS'].ravel()[data['ravensburger_cells']]
        depth_nodes_img = data['DEPTH_NODES'].ravel()[data['ravensburger_nodes']]
        mag_img = np.sqrt(u_img**2 + v_img**2)

        # Plot scanned height
        self.im_height = self.ax.imshow(
            warped_height,
            'jet',
            alpha=1,
            vmin=data['z'][0],
            vmax=data['z'][-1],
            visible=False
        )

        # plot satellite image background
        if self.background is not None:
            self.im_background = self.ax.imshow(
                self.background,
                extent=[0, 640, 480, 0]
            )

        # Plot waterdepth
        # data['hh'] in xbeach
        self.im_waterlevel = self.ax.imshow(
            (waterlevel_img - depth_cells_img),
            cmap='Blues',
            alpha=.3 if self.background is not None else 1.0,
            vmin=0,
            vmax=3,
            visible=True
        )

        # Plot bed level
        self.im_depth_cells = self.ax.imshow(
            depth_cells_img,
            cmap=terrajet2,  # 'gist_earth',
            alpha=1,
            vmin=data['z'][0],
            vmax=data['z'][-1],
            visible=False
        )

        # Plot flow magnitude
        self.im_mag = self.ax.imshow(
            mag_img,
            'jet',
            alpha=1,
            vmin=0,
            visible=False
        )

        if data.get('debug'):
            self.ct_depth_cells = self.ax.contour(depth_cells_img, colors='k')
            self.ax.clabel(self.ct_depth_cells, inline=1, fontsize=10)

        # Plot particles
        self.im_flow = self.ax.imshow(
            self.lic,
            alpha=0.8,
            interpolation='none',
            visible=True
        )

        # self.ax.set_xlim(xlim[0] + 80, xlim[1] - 80)
        # self.ax.set_ylim(ylim[0] + 80, ylim[1] - 80)
        self.ax.axis('tight')
        # self.ax.axis('off')
        self.fig.canvas.draw()
        self.fig.canvas.mpl_connect('button_press_event', self.notify)
        self.fig.canvas.mpl_connect('key_press_event', self.notify)

    #@profile
    def update(self, data):
        i = next(self.counter)

        #############################################
        # Update camera visualisation
        warped_height = cv2.warpPerspective(
            data['height'],
            np.array(data['img2box']),
            data['height'].shape[::-1]
        )

        # Update scanned height
        self.im_height.set_data(warped_height)

        #############################################
        # Update model parameters
        #
        # Transform velocity
        x_cells_box, y_cells_box = transform(
            data['X_CELLS'].ravel(),
            data['Y_CELLS'].ravel(),
            data['model2box']
        )

        # transform vectors
        x_cells_u_box, y_cells_v_box = transform(
            data['X_CELLS'].ravel() + data['U'].ravel(),
            data['Y_CELLS'].ravel() + data['V'].ravel(),
            data['model2box']
        )
        # not sure whe don't use U
        u_in_img = x_cells_u_box - x_cells_box
        v_in_img = y_cells_v_box - y_cells_box

        # Convert to simple arrays
        depth_nodes_img = data['DEPTH_NODES'].ravel()[data['ravensburger_nodes']]
        waterlevel_img = data['WATERLEVEL'].ravel()[data['ravensburger_cells']]
        u_img = u_in_img[data['ravensburger_cells']]
        v_img = v_in_img[data['ravensburger_cells']]
        depth_cells_img = data['DEPTH_CELLS'].ravel()[data['ravensburger_cells']]
        mag_img = np.sqrt(u_img**2 + v_img**2)

        # Update raster plots
        self.im_waterlevel.set_data(waterlevel_img - depth_cells_img)
        self.im_depth_cells.set_data(depth_cells_img)
        self.im_mag.set_data(mag_img)

        #################################################
        # Compute liquid added to the model
        #
        # Multiplier on the flow velocities
        scale = data.get('scale', 10.0)
        flow = np.dstack([u_img, v_img]) * scale


        # compute new flow timestep
        self.lic = warp_flow(
            self.lic.astype('float32'),
            flow.astype('float32')
        )
        # fade out
        # self.lic[..., 3] -= 0.01
        # but not < 0
        self.lic[..., 3][self.lic[..., 3] < 0] = 0
        self.lic[..., 3][data['cell_mask']] = 0

        # Update liquid
        self.im_flow.set_data(self.lic)

        # Put in new white dots (to be plotted next time step)
        for u, v in zip(np.random.random(4), np.random.random(4)):
            rgb = (1.0, 1.0, 1.0)
            # make sure outline has the same color
            # create a little dot
            r, c = skimage.draw.circle(v * HEIGHT, u * WIDTH, 4,
                                       shape=(HEIGHT, WIDTH))
            # Don't plot on (nearly) dry cells
            if (
                    waterlevel_img[int(v * HEIGHT), int(u * WIDTH)] -
                    depth_nodes_img[int(v * HEIGHT), int(u * WIDTH)]
            ) < 0.5:
                continue
            # if zk_img[int(v * HEIGHT), int(u * WIDTH)] > 0:
            #     continue
            self.lic[r, c, :] = tuple(rgb) + (1, )

        # Remove liquid on dry places
        self.lic[depth_cells_img >= waterlevel_img, 3] = 0.0
        self.lic[depth_nodes_img >= waterlevel_img, 3] = 0.0

        #################################################
        # Draw updated canvas
        #
        # TODO: this can be faster, this also redraws axis
        # self.fig.canvas.draw()
        # for artist in [self.im_zk, self.im_s1, self.im_flow]:
        #     self.ax.draw_artist(artist)
        # self.fig.canvas.blit(self.ax.bbox)
        # self.ax.redraw_in_frame()
        # interact with window and click events
        self.fig.canvas.draw()
        try:
            self.fig.canvas.flush_events()
        except NotImplementedError:
            pass
