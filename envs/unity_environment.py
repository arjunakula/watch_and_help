from utils import utils_environment as utils
import sys
import os
curr_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(f'{curr_dir}/../../virtualhome/simulation/')

from environment.unity_environment import UnityEnvironment as BaseUnityEnvironment
from evolving_graph import utils as utils_env
import pdb
import numpy as np

class UnityEnvironment(BaseUnityEnvironment):


    def __init__(self,
                 num_agents=2,
                 max_episode_length=200,
                 env_task_set=None,
                 observation_types=None,
                 agent_goals=None,
                 use_editor=False,
                 base_port=8080,
                 port_id=0,
                 executable_args={},
                 recording_options={'recording': False, 
                    'output_folder': None, 
                    'file_name_prefix': None,
                    'cameras': 'PERSON_FROM_BACK',
                    'modality': 'normal'},
                 seed=123):

        if agent_goals is not None:
            self.agent_goals = agent_goals
        else:
            self.agent_goals = ['full' for _ in range(num_agents)]
        
        self.task_goal, self.goal_spec = {0: {}, 1: {}}, {0: {}, 1: {}}
        self.env_task_set = env_task_set
        super(UnityEnvironment, self).__init__(
            num_agents=num_agents,
            max_episode_length=max_episode_length,
            observation_types=observation_types,
            use_editor=use_editor,
            base_port=base_port,
            port_id=port_id,
            executable_args={},
            recording_options=recording_options,
            seed=seed
            )
        self.full_graph = None

    

    def reward(self):
        reward = 0.
        done = True
        # print(self.goal_spec)
        satisfied, unsatisfied = utils.check_progress(self.get_graph(), self.goal_spec[0])
        for key, value in satisfied.items():
            preds_needed, mandatory, reward_per_pred = self.goal_spec[0][key]
            # How many predicates achieved
            value_pred = min(len(value), preds_needed)
            reward += value_pred * reward_per_pred

            if mandatory and unsatisfied[key] > 0:
                done = False

        self.prev_reward = reward
        return reward, done, {'satisfied_goals': satisfied}




    def get_goal(self, task_spec, agent_goal):
        if agent_goal == 'full':
            pred = [x for x, y in task_spec.items() if y > 0 and x.split('_')[0] in ['on', 'inside']]
            # object_grab = [pr.split('_')[1] for pr in pred]
            # predicates_grab = {'holds_{}_1'.format(obj_gr): [1, False, 2] for obj_gr in object_grab}
            res_dict = {goal_k: [goal_c, True, 2] for goal_k, goal_c in task_spec.items()}
            # res_dict.update(predicates_grab)
            return res_dict
        elif agent_goal == 'grab':
            candidates = [x.split('_')[1] for x,y in task_spec.items() if y > 0 and x.split('_')[0] in ['on', 'inside']]
            object_grab = self.rnd.choice(candidates)
            # print('GOAL', candidates, object_grab)
            return {'holds_'+object_grab+'_'+'1': [1, True, 10], 'close_'+object_grab+'_'+'1': [1, False, 0.1]}
        elif agent_goal == 'put':
            pred = self.rand.choice([x for x, y in task_spec.items() if y > 0 and x.split('_')[0] in ['on', 'inside']])
            object_grab = pred.split('_')[1]
            return {
                pred: [1, True, 60],
                'holds_' + object_grab + '_' + '1': [1, False, 2],
                'close_' + object_grab + '_' + '1': [1, False, 0.05]

            }
        else:
            raise NotImplementedError

    def reset(self, environment_graph=None, task_id=None):

        # Make sure that characters are out of graph, and ids are ok
        if task_id is None:
            task_id = self.rnd.choice(list(range(len(self.env_task_set))))
        print('TaskId: {}'.format(task_id))
        env_task = self.env_task_set[task_id]

        self.task_id = env_task['task_id']
        self.init_graph = env_task['init_graph']
        self.init_rooms = env_task['init_rooms']
        self.task_goal = env_task['task_goal']

        self.task_name = env_task['task_name']

        old_env_id = self.env_id
        self.env_id = env_task['env_id']
        print("Resetting", self.env_id, self.task_id)

        # TODO: in the future we may want different goals
        self.goal_spec = {agent_id: self.get_goal(self.task_goal[agent_id], self.agent_goals[agent_id])
                          for agent_id in range(self.num_agents)}
        
        if False: # old_env_id == self.env_id:
            print("Fast reset")
            self.comm.fast_reset()
        else:
            self.comm.reset(self.env_id)

        s,g = self.comm.environment_graph()
        edge_ids = set([edge['to_id'] for edge in g['edges']] + [edge['from_id'] for edge in g['edges']])
        node_ids = set([node['id'] for node in g['nodes']])
        if len(edge_ids - node_ids) > 0:
            pdb.set_trace()


        if self.env_id not in self.max_ids.keys():
            max_id = max([node['id'] for node in g['nodes']])
            self.max_ids[self.env_id] = max_id

        max_id = self.max_ids[self.env_id]
        if environment_graph is not None:
            # TODO: this should be modified to extend well
            # updated_graph = utils.separate_new_ids_graph(environment_graph, max_id)
            updated_graph = environment_graph
            s, g = self.comm.environment_graph()
            udpated_graph = self.remove_floor(updated_graph, g)
            success, m = self.comm.expand_scene(updated_graph)
        else:
            updated_graph = env_task['init_graph']
            s, g = self.comm.environment_graph()
            udpated_graph = self.remove_floor(updated_graph, g)
            updated_graph = utils.separate_new_ids_graph(updated_graph, max_id)
            success, m = self.comm.expand_scene(updated_graph)
        
        if not success:
            print("Error expanding scene")
            pdb.set_trace()
            return None
        self.offset_cameras = self.comm.camera_count()[1]

        if self.init_rooms[0] not in ['kitchen', 'bedroom', 'livingroom', 'bathroom']:
            rooms = self.rnd.sample(['kitchen', 'bedroom', 'livingroom', 'bathroom'], 2)
        else:
            rooms = list(self.init_rooms)

        for i in range(self.num_agents):
            if i in self.agent_info:
                self.comm.add_character(self.agent_info[i], initial_room=rooms[i])
            else:
                self.comm.add_character()

        _, self.init_unity_graph = self.comm.environment_graph()


        self.changed_graph = True
        graph = self.get_graph()
        self.rooms = [(node['class_name'], node['id']) for node in graph['nodes'] if node['category'] == 'Rooms']
        self.id2node = {node['id']: node for node in graph['nodes']}

        obs = self.get_observations()
        self.steps = 0
        self.prev_reward = 0.
        return obs


    def get_observation(self, agent_id, obs_type, info={}):
        if obs_type == 'partial':
            # agent 0 has id (0 + 1)
            curr_graph = self.get_graph()
            curr_graph = utils.inside_not_trans(curr_graph)
            self.full_graph = curr_graph
            return utils_env.get_visible_nodes(curr_graph, agent_id=(agent_id+1))

        elif obs_type == 'full':
            return self.get_graph()

        elif obs_type == 'visible':
            # Only objects in the field of view of the agent
            raise NotImplementedError

        elif obs_type == 'image':
            camera_ids = [self.num_static_cameras + agent_id * self.num_camera_per_agent + self.CAMERA_NUM]
            if 'image_width' in info:
                image_width = info['image_width']
                image_height = info['image_height']
            else:
                image_width, image_height = self.default_image_width, self.default_image_height

            s, images = self.comm.camera_image(camera_ids, mode=obs_type, image_width=image_width, image_height=image_height)
            if not s:
                pdb.set_trace()
            return images[0]
        else:
            raise NotImplementedError

    def remove_floor(self, updated_graph, curr_graph):
        # translate_prefab = {
        #     'Cupcake_1': 'DHP_PRE_Pink_cupcake_1024',
        #     'Cupcake_2': 'DHP_PRE_Rainbow_cupcake_1024',
        #     'PRE_PRO_Box_02': 'PRE_PRO_Box_01'
        # }
        # ipdb.set_trace()
        floor_none_ids = sorted([node['id'] for node in updated_graph['nodes'] if node['prefab_name'] == "Floor" or 
            node['id'] == 197 or node['prefab_name'] == 'mH_Bucket01_s'])

        node_id_mapping = {}
        updated_graph['nodes'] = [node for node in updated_graph['nodes'] if node['id'] not in floor_none_ids]
        updated_graph['edges'] = [edge for edge in updated_graph['edges'] if edge['from_id'] not in floor_none_ids and edge['to_id'] not in floor_none_ids]
        
        for node in updated_graph['nodes']:
            curr_idx = len([it for it, elem in enumerate(floor_none_ids) if elem < node['id']])
            new_id = node['id'] - curr_idx
            node_id_mapping[node['id']] = node['id'] - curr_idx
            node['id'] = new_id

            # if node['prefab_name'] in translate_prefab:
            #     node['prefab_name'] = translate_prefab[node['prefab_name']]
        
        for edge in updated_graph['edges']:
            edge['from_id'] = node_id_mapping[edge['from_id']]
            edge['to_id'] = node_id_mapping[edge['to_id']]
        updated_graph['nodes'] = [node for node in updated_graph['nodes'] if node['class_name'] != 'kitchencabinets']
        updated_graph['nodes'] += [node for node in curr_graph['nodes'] if node['class_name'] == 'kitchencabinet']
        return updated_graph