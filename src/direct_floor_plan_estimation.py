from cv2 import sepFilter2D
from urllib3 import Retry
from src.scale_recover import ScaleRecover
from src.solvers.theta_estimator import ThetaEstimator
from src.solvers.plane_estimator import PlaneEstimator
from src.data_structure import OCGPatches, room
from .data_structure import Room
from utils.geometry_utils import find_N_peaks
import numpy as np
import matplotlib.pyplot as plt

class DirectFloorPlanEstimation:

    def __init__(self, data_manager):
        self.dt = data_manager
        self.scale_recover = ScaleRecover(self.dt)
        self.theta_estimator = ThetaEstimator(self.dt)
        self.plane_estimator = PlaneEstimator(self.dt)
        self.global_ocg_patch = OCGPatches(self.dt)
        self.list_ly = []
        self.list_pl = []

        self.list_rooms = []

        self.curr_room = None
        self.is_initialized = False

        print("DirectFloorPlanEstimation initialized successfully")

    def estimate(self, layout):
        """
        It add the passed Layout to the systems and estimated the floor plan
        """

        if not self.is_initialized:
            self.initialize(layout)
            return

        if not self.initialize_layout(layout):
            return layout.is_initialized

        if self.eval_new_room_creteria(layout):
            # self.curr_room = self.select_room(layout)
            self.curr_room = None
            if self.curr_room is None:
                # ! New Room in the system
                self.curr_room = Room(self.dt)
                # ! Initialize current room
                if self.curr_room.initialize(layout):
                    self.list_rooms.append(room)
                return 

        self.update_data(layout)

    def update_data(self, layout):
        """
        Updates all data in the system given the new current passed layout
        """
        if not layout.is_initialized:
            raise ValueError("Passed Layout must be initialized first...")

        self.curr_room.add_layout(layout)
        self.add_layout(layout)

    def add_layout(self, layout):
        self.list_ly.append(layout)
        [self.list_pl.append(pl) for pl in layout.list_pl]
        # self.global_ocg_patch.add_patch(layout.patch)

    def initialize_layout(self, layout):
        """
        Initializes the passed layout. This function has to be applied to all 
        layout before any FEP module
        """
        # layout.compute_cam2boundary()
        # layout.patch.initialize()
        self.apply_vo_scale(layout)
        self.compute_planes(layout)
        layout.initialize()
        layout.is_initialized = True
        return layout.is_initialized

    def initialize(self, layout):
        """
        Initializes the system
        """
        self.is_initialized = False
        if not self.scale_recover.estimate_vo_scale():
            return self.is_initialized

        # ! Create very first Room
        self.curr_room = Room(self.dt)

        # ! Initialize current layout
        if not self.initialize_layout(layout):
            return self.is_initialized

        # ! Initialize current room
        if not self.curr_room.initialize(layout):
            return self.is_initialized

        self.list_ly.append(layout)
        [self.list_pl.append(pl) for pl in layout.list_pl]

        # ! Initialize Global Patches
        if not self.global_ocg_patch.initialize(layout.patch):
            return self.is_initialized

        # ! Only if the room is successfully initialized
        self.list_rooms.append(self.curr_room)

        self.is_initialized = True
        return self.is_initialized

    def eval_new_room_creteria(self, layout):
        """
        Evaluates whether the passed layout triggers a new room
        """
        if not layout.is_initialized:
            raise ValueError("Layout must be initialized before...")

        pose_uv = self.curr_room.local_ocg_patches.project_xyz_to_uv(
            xyz_points=layout.pose_est.t.reshape((3, 1))
        )
        room_ocg_map = self.curr_room.local_ocg_patches.ocg_map
        
        # curr_room_idx = self.list_rooms.index(self.curr_room)
        # tmp_ocg = self.global_ocg_patch.ocg_map[:, :, curr_room_idx]
        tmp_ocg = room_ocg_map
        eval_pose = tmp_ocg[pose_uv[1, :], pose_uv[0, :]]/tmp_ocg.max()
        self.curr_room.p_pose.append(eval_pose)
        plt.figure(0)
        plt.clf()
        plt.subplot(121)   
        room_ocg_map[pose_uv[1, :], pose_uv[0, :]] = -1
        plt.imshow(room_ocg_map)
        plt.subplot(122)   
        plt.plot(self.curr_room.p_pose)
        plt.draw()
        plt.waitforbuttonpress(0.1)
        
        if eval_pose < self.dt.cfg["room_id.ocg_threshold"]:
            return True
        else:
            return False

    def apply_vo_scale(self, layout):
        """
        Applies VO-scale to the passed layout
        """
        layout.apply_vo_scale(self.scale_recover.vo_scale)
        print("VO-scale {0:2.2f} applied to Layout {1:1d}".format(
            self.scale_recover.vo_scale,
            layout.idx)
        )

    def compute_planes(self, layout):
        """
        Computes Planes in the passed layout
        """
        corn_idx, _ = find_N_peaks(layout.ly_data[2, :], r=100)

        pl_hypotheses = [layout.boundary[:, corn_idx[i]:corn_idx[i + 1]] for i in range(len(corn_idx) - 1)]
        pl_hypotheses.append(np.hstack((layout.boundary[:, corn_idx[-1]:], layout.boundary[:, 0:corn_idx[0]])))

        list_pl = []
        for pl_h in pl_hypotheses:
            pl, flag_success = self.plane_estimator.estimate_plane(pl_h)
            if not flag_success:
                continue

            list_pl.append(pl)

        layout.list_pl = list_pl
