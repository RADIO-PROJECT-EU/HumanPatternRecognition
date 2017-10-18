#!/usr/bin/env python
import roslib, rospy
import numpy as np
import csv
from sensor_msgs.msg import LaserScan
from laser_wall_extraction.msg import BufferMsg
from laser_wall_extraction.msg import WallVizMsg
from radio_services.srv import InstructionWithAnswer


wall_flag = 0
w_index = 0 #current laser scan used (wall index)
scan2wall_limit = 3 #how many laser scans to use in order to create the walls
range_limit = 10
timewindow = 40
fr_index = 1

z = 0
z_end = 0.0
dt = 25;#period in ms (dt between scans)
speed = 5;#human walking speed in km/h
z_scale = float(speed*dt) / float(3600)

use_overlap = True
overlap_part = []

buffer_publisher = None
frame_id = ''

publish_viz = False
viz_publisher = None
wall_cart = None

################################################
#used only for testing the hypothetical laser scanner with worse quality

scan_freq = 1 #because scantime_laser1 = 25msec and scantime_laser2 = 100msec
state = 0  #denotes which frames we ll keep

###############################################

running = False
scan_sub = None
scan_topic = ''

def init():
    global range_limit, timewindow, use_overlap, buffer_publisher, frame_id, dt, speed_, z_scale
    global publish_viz, viz_publisher, running, scan_sub, scan_topic

    rospy.init_node('laser_wall_extraction')

    scan_topic = rospy.get_param('~scan_topic','scan')
    timewindow = rospy.get_param('~timewindow', 40)
    range_limit = rospy.get_param('~range_limit', 10)
    use_overlap = rospy.get_param('~use_overlap', True)
    buffer_topic = rospy.get_param('~buffer_topic','~buffer')
    frame_id = rospy.get_param('~frame_id','laser_link')
    dt = rospy.get_param('~dt', 25)
    speed_ = rospy.get_param('~human_speed', 5)
    publish_viz = rospy.get_param('~publish_viz', False)
    viz_topic = rospy.get_param('~viz_topic', "~viz_req")
    running = rospy.get_param('~run_on_startup', False)

    z_scale = float(speed_*dt) / float(3600)

    print 'z scale = ',z_scale 

    rospy.Service('/human_pattern_recognition/laser_wall_extraction/node_state_service', InstructionWithAnswer, nodeStateCallback)

    if running:
        scan_sub = rospy.Subscriber(scan_topic, LaserScan, wall_extraction)

    buffer_publisher = rospy.Publisher(buffer_topic, BufferMsg, queue_size=10)
    
    if publish_viz:
        viz_publisher = rospy.Publisher(viz_topic, WallVizMsg, queue_size=1)

    while not rospy.is_shutdown():  
        rospy.spin()

def wall_extraction(laser_data):
    global wall_flag, w_index, scan2wall_limit, range_limit, timewindow, fr_index, buffer_publisher
    global z, z_scale, z_end
    global mybuffer, wall, sampling, phi, mybuffer_tmp
    global use_overlap, overlap_part, frame_id
    global viz_publisher, publish_viz, wall_cart

    global scan_freq, state

    laser_ranges = list(laser_data.ranges)
    
    for i in range(0, len(laser_ranges)):
        if laser_ranges[i]>range_limit:
                j = i - 1;
                while  laser_ranges[j] > range_limit:
                        j = j - 1;
                        if j == 0:
                            break;
                laser_ranges[i] = laser_ranges[j];

    
    if wall_flag == 0:
        if w_index == 0:
            sampling = np.arange(0,len(np.array(laser_ranges)),2)#apply sampling e.g every 2 steps

            #wall data now contains the scan ranges
            wall = np.array(laser_ranges)

            mybuffer = wall
            #get indexes of scans >= range_limit
            filter=np.where(wall >= range_limit)
            #set those scans to maximum range
            wall[filter] = range_limit
            w_index=w_index+1
            
        if w_index<scan2wall_limit: #loop until you have enough scans to set walls
            wall = np.array(laser_ranges)
            filter = np.where(wall >= range_limit)
            wall[filter] = range_limit
            mybuffer = np.vstack((mybuffer,wall ))  #  add to buffer with size=(wall_index x 360)
            w_index = w_index+1

        if w_index==scan2wall_limit:
            mybuffer = np.vstack((mybuffer,wall ))
            phi = np.arange(laser_data.angle_min,laser_data.angle_max,laser_data.angle_increment)[sampling]
            wall = (np.min(mybuffer, axis=0)[sampling])-0.1 #select min of measurements
            wall_cart = np.array(pol2cart(wall,phi,0)) #convert to Cartesian
            wall_flag = 1
            print 'walls are set'
            if publish_viz:
                wvm = WallVizMsg()
                wvm.x = wall_cart[:,0]
                wvm.y = wall_cart[:,1]
                viz_publisher.publish(wvm)
       
                
    else:
        if (state%scan_freq) == 0:
		if publish_viz:
		        wvm = WallVizMsg()
		        wvm.x = wall_cart[:,0]
		        wvm.y = wall_cart[:,1]
		        viz_publisher.publish(wvm)
		#walls are set, process scans
		ranges = np.array(laser_ranges)[sampling]
		filter = np.where(ranges < wall) # filter out walls
		ranges = ranges[filter]
		theta = phi[filter]


		if (len(ranges)>3): #each scan should consist of at least 3 points to be valid
		    C = np.array(pol2cart(ranges, theta, z) ) #convert to Cartesian

		    if (fr_index == 1 ):
		            if (len(overlap_part) == 0 or not use_overlap):
                                z = z_end
		                mybuffer = C #mybuffer is the cartesian coord of the first scan
		                #mybuffer_tmp = [C]
		            else:
		                mybuffer =  np.concatenate((overlap_part,C), axis=0 )
		                overlap_part = []
		                #mybuffer_tmp = [C]
		    else :
		        mybuffer = np.concatenate((mybuffer,C), axis=0 )  #  add the next incoming scans to mybuffer until you have <timewindow>scans
		        #mybuffer_tmp.append((mybuffer_tmp,[C]))

		        if(use_overlap):
		            if fr_index == (timewindow-1):
		                if (len(overlap_part) == 0):
		                    overlap_part = np.array(pol2cart(ranges,theta,0.0))
		                else:
		                    overlap_part = np.concatenate((overlap_part, np.array(pol2cart(ranges,theta,0.0)) ) , axis=0)

		    if (fr_index == timewindow ):
		        #define overlap_part as the 2 last frames of the current timewindow in order to be overlaped with the first frame of the next timewindow.
		        #It is neccessary for the overlap_trace function
		        if(use_overlap):
		            overlap_part = np.concatenate((overlap_part, np.array(pol2cart(ranges,theta,0.0)) ) , axis=0)

		        mybuffer=mybuffer[np.where( mybuffer[:,0] > 0.2),:][0] #mishits safety margin
		        mybuffer=mybuffer[np.where( mybuffer[:,0] < range_limit),:][0]#ignore distant points


		        if len(mybuffer > 3): #at least 3 points are needed to form a cluster
		            buffmsg = BufferMsg()
		            buffmsg.header.stamp = rospy.Time.now()
		            buffmsg.header.frame_id = frame_id
		            buffmsg.x = mybuffer[:,0]
		            buffmsg.y = mybuffer[:,1]
		            buffmsg.z = mybuffer[:,2]
		            buffmsg.scan_time = laser_data.scan_time
		            buffer_publisher.publish(buffmsg)

                        if not use_overlap:
                            z_end = z + z_scale

		        fr_index = 0
		        z = - z_scale
		    z = z + z_scale
		    fr_index = fr_index + 1
		else:
		    buffmsg = BufferMsg()
		    buffmsg.header.stamp = rospy.Time.now()
		    buffmsg.header.frame_id = frame_id
		    buffmsg.x = []
		    buffmsg.y = []
		    buffmsg.z = []
		    buffer_publisher.publish(buffmsg)
                    #z_end = 0

        state = state + 1

##
## @brief      This function is called when the corresponding service is called
##             and based on the parameter passed, either changes its state and
##             returns the new state, or just returns the current state.
##             0: Change the current node state to WAITING (false) and return the current node state.
##             1: Change the current node state to RUNNING (true), return the current node state (and do not change the mode).
##            -1: Return the current node state.
##
## @param      req   The requested action
##
## @return     The current state of the node
##
def nodeStateCallback(req):
    global running, scan_sub, scan_topic
    global wall_flag, w_index, fr_index, z
    global z_end, overlap_part, frames_array, use_overlap
    # TODO use the response! (for now I just print it!)
    if req.command == 0 and running:
        running = False
        scan_sub.unregister()
        print 'Stopped laser wall extraction!'
        rospy.wait_for_service('/human_pattern_recognition/laser_clustering/node_state_service')
        try:
            node_state_service = rospy.ServiceProxy('/human_pattern_recognition/laser_clustering/node_state_service', InstructionWithAnswer)
            req = False
            res = node_state_service(req)
            print res
            if use_overlap:
                rospy.wait_for_service('/human_pattern_recognition/laser_overlap_trace/node_state_service')
                node_state_service = rospy.ServiceProxy('/human_pattern_recognition/laser_overlap_trace/node_state_service', InstructionWithAnswer)
                res = node_state_service(req)
                print res
            rospy.wait_for_service('/human_pattern_recognition/laser_analysis/node_state_service')
            node_state_service = rospy.ServiceProxy('/human_pattern_recognition/laser_analysis/node_state_service', InstructionWithAnswer)
            res = node_state_service(req)
            print res
            wall_flag = 0
            w_index = 0
            fr_index = 1
            z = 0
            z_end = 0.0
            overlap_part = []
            frames_array = []
        except rospy.ServiceException, e:
            print "Service call failed: %s"%e
    elif req.command == 1 and not running:
        running = True
        wall_flag = 0
        w_index = 0
        fr_index = 1
        z = 0
        z_end = 0.0
        overlap_part = []
        frames_array = []
        scan_sub = rospy.Subscriber(scan_topic, LaserScan, wall_extraction)
        print 'Started laser wall extraction!'
        rospy.wait_for_service('/human_pattern_recognition/laser_clustering/node_state_service')
        try:
            node_state_service = rospy.ServiceProxy('/human_pattern_recognition/laser_clustering/node_state_service', InstructionWithAnswer)
            req = True
            res = node_state_service(req)
            print res
            if use_overlap:
                rospy.wait_for_service('/human_pattern_recognition/laser_overlap_trace/node_state_service')
                node_state_service = rospy.ServiceProxy('/human_pattern_recognition/laser_overlap_trace/node_state_service', InstructionWithAnswer)
                res = node_state_service(req)
                print res
            rospy.wait_for_service('/human_pattern_recognition/laser_analysis/node_state_service')
            node_state_service = rospy.ServiceProxy('/human_pattern_recognition/laser_analysis/node_state_service', InstructionWithAnswer)
            res = node_state_service(req)
            print res
        except rospy.ServiceException, e:
            print "Service call failed: %s"%e
    return running


#convert polar coordinates to cartesian
def pol2cart(r,theta,zed):
    x=np.multiply(r,np.cos(theta))
    y=np.multiply(r,np.sin(theta))
    z=np.ones(r.size)*zed
    C=np.array([x,y,z]).T
    return C


if __name__ == '__main__':
    init() 
