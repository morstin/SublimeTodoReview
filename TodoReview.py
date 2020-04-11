'''
SublimeTodoReview
A SublimeText 3 plugin for reviewing todo (and other) comments within your code.

@author Jonathan Delgado (Initial Repo by @robcowie and ST3 update by @dnatag)
'''

import datetime
import fnmatch
import io
import itertools
import os
import re
import sublime
import sublime_plugin
import sys
import threading
import timeit
import unicodedata #added by JN
import math #added by JN

gFileList = {}
gResults = {}

class Settings():
	def __init__(self, view, args):
		self.user = sublime.load_settings('TodoReview.sublime-settings')
		if not args:
			self.proj = view.settings().get('todoreview', {})
		else:
			self.proj = args

	def get(self, key, default):
		return self.proj.get(key, self.user.get(key, default))

class Engine():
	def __init__(self, dirpaths, filepaths, view):
		self.view = view
		self.dirpaths = dirpaths
		self.filepaths = filepaths
		if settings.get('case_sensitive', False):
			case = 0
		else:
			case = re.IGNORECASE
		patt_patterns = settings.get('patterns', {})
		patt_files = settings.get('exclude_files', [])
		patt_folders = settings.get('exclude_folders', [])
		match_patterns = '|'.join(patt_patterns.values())
		match_files = [fnmatch.translate(p) for p in patt_files]
		match_folders = [fnmatch.translate(p) for p in patt_folders]

		self.resolve_symlinks = settings.get('resolve_symlinks', True)
		self.patterns = re.compile(match_patterns, case) #'TODO[\\s]*?:[\\s]*(?P<todo>.*)$'
		self.priority = re.compile(r'\(([0-9]{1,2})\)')
		self.startdate = re.compile(r'(?<=@start)\(([^]]+\-[^]]+\-[^]]+)\)') #added by JN
		self.exclude_files = [re.compile(p) for p in match_files]
		self.exclude_folders = [re.compile(p) for p in match_folders]
		self.open = self.view.window().views()
		self.open_files = [v.file_name() for v in self.open if v.file_name()]

		self.depth = settings.get('render_folder_depth', 1)
		self.renderIncludeFolder = settings.get('render_include_folder', False)

	def files(self):
		seen_paths = []
		for dirpath in self.dirpaths:
			dirpath = self.resolve(dirpath)
			for dirp, dirnames, filepaths in os.walk(dirpath, followlinks=True):
				if any(p.search(dirp) for p in self.exclude_folders):
					continue
				for filepath in filepaths:
					self.filepaths.append(os.path.join(dirp, filepath))
		for filepath in self.filepaths:
			p = self.resolve(filepath)
			if p in seen_paths:
				continue
			if any(p.search(filepath) for p in self.exclude_folders):
				continue
			if any(p.search(filepath) for p in self.exclude_files):
				continue
			seen_paths.append(p)
			yield p

	def extract(self, files):
		self.prioritysomeday = int(settings.get('priority_from_which_its_someday', 80))
		encoding = settings.get('encoding', 'utf-8')
		for p in files:
			global gFileList
			global gResults
			resultsinfile = []
			lastSeenChangeDate = gFileList.get(p)
			changeDate = os.path.getmtime(p)
			if changeDate == lastSeenChangeDate:
				#file not changed since last read
				itemlist = [d for d in gResults if d['file'] == p]
				for item in itemlist:
					resultsinfile.append((item['patt'], item['note'], item['line']))
			else:
				#file changed since last read
				gFileList[p] = changeDate
				try:
					if p in self.open_files:
						for view in self.open:
							if view.file_name() == p:
								f = []
								lines = view.lines(sublime.Region(0, view.size()))
								for line in lines:
									f.append(view.substr(line))
								break
					else:
						f = io.open(p, 'r', encoding=encoding)
					for num, line in enumerate(f, 1):
						for result in self.patterns.finditer(line):
							#resultsinfile.extend(result.groupdict().items())
							for item in result.groupdict().items():
								resultsinfile.append((item[0], item[1], num))
				except(IOError, UnicodeDecodeError):
					f = None
				finally:
					if f is not None and type(f) is not list:
						f.close()

			for patt, note, num in resultsinfile:
				if not note and note != '':
					continue
				priority_match = self.priority.search(note)
				if(priority_match):	priority = int(priority_match.group(1))
				else:				priority = 50
				#added by JN 
				filename = self.getFileName(p, num)
				startdate_str = self.getStartdate(note)
				timeliness = self.getTimeliness(startdate_str)
				timelinessgroup = self.getTimelinessGroup(priority, startdate_str, timeliness)
				#end added by JN
				yield {
					'file': p,
					'filename': filename,   #added by JN
					'patt': patt,
					'note': note,
					'line': num,
					'priority': priority,
					'startdate': startdate_str,  #added by JN
					'timeliness': abs(timeliness),  #added by JN
					'timelinessgroup': timelinessgroup  #added by JN
				}

			thread.increment()


	def debugStr(self, str):
		for i in str:
			if ord(i) < 127:
				chartype =  'ascii'
			else:
				chartype = 'multibytes'
			print(i, ' ', ord(i), chartype)

	def debugStr2(self, str):
		for i, c in enumerate(str):
			print(i, '%04x' % ord(c), unicodedata.category(c), end=" ")
			print(unicodedata.name(c))

	def process(self):
		return self.extract(self.files())

	def resolve(self, directory):
		if self.resolve_symlinks:	return os.path.realpath(os.path.expanduser(os.path.abspath(directory)))
		else:						return os.path.expanduser(os.path.abspath(directory))

	#added by JN
	def getFileName(self, file, line):
		if self.renderIncludeFolder:
			if self.depth == 'auto':
				for folder in sublime.active_window().folders():
					if file.startswith(folder):
						file_a = os.path.relpath(file, folder)
						break
				file_a = file.replace('\\', '/')
			else:
				file_a = os.path.dirname(file).replace('\\', '/').split('/')
				file_a = '/'.join(file_a[-self.depth:] + [os.path.basename(file)])
		else:
			file_a = os.path.basename(file)
		file_a = unicodedata.normalize('NFC', file_a) #very important - otherwise strage effects with ü which an also be encoded as u¨ - the two dots being chr(776)
		return '%f:%l' \
			.replace('%f', file_a) \
			.replace('%l', str(line))

	def getStartdate(self, note):
		startdate_match = self.startdate.search(note)
		if(startdate_match):
			startdate_str = str(startdate_match.group(1))
		else:
			startdate_str = ""
		return startdate_str

	def getTimeliness(self, startdate_str):
		if startdate_str != '':
			startdate = datetime.date(int(startdate_str[0:4]),int(startdate_str[5:7]),int(startdate_str[8:10]))
			today = datetime.date.today()
			delta = today - startdate
			timeliness = delta.days
		else:
			timeliness = 99
		return timeliness

	def getTimelinessGroup(self, priority, startdate_str, timeliness):
		if startdate_str == '':
			prio_someday = range(self.prioritysomeday, 100)
			if priority in prio_someday:	timelinessgroup = 'Someday'
			else:							timelinessgroup = 'Important'
		else:
			if timeliness < 0:				timelinessgroup = 'Future'
			else:							timelinessgroup = 'Now'
		return timelinessgroup
	#end added by JN

class Thread(threading.Thread):
	def __init__(self, engine, callback):
		self.i = 0
		self.engine = engine
		self.callback = callback
		self.lock = threading.RLock()
		threading.Thread.__init__(self)

	def run(self):
		self.start = timeit.default_timer()
		if sys.version_info < (3,0,0):
			sublime.set_timeout(self.thread, 1)
		else:
			self.thread()

	def thread(self):
		results = list(self.engine.process()) #function calling yield in extract
		self.callback(results, self.finish(), self.i)

	def finish(self):
		return round(timeit.default_timer() - self.start, 2)

	def increment(self):
		with self.lock:
			self.i += 1
			sublime.status_message("TodoReview: {0} files scanned".format(self.i))

class TodoReviewCommand(sublime_plugin.TextCommand):
	def run(self, edit, **args):
		global settings, thread
		filepaths = []
		self.args = args
		window = self.view.window()
		paths = args.get('paths', None)
		settings = Settings(self.view, args.get('settings', False))
		if args.get('current_file', False):
			if self.view.file_name():
				paths = []
				filepaths = [self.view.file_name()]
			else:
				print('TodoReview: File must be saved first')
				return
		else:
			if not paths and settings.get('include_paths', False):
				paths = settings.get('include_paths', False)
			if args.get('open_files', False):
				filepaths = [v.file_name() for v in window.views() if v.file_name()]
			if not args.get('open_files_only', False):
				if not paths:
					paths = window.folders()
				else:
					for p in paths:
						if os.path.isfile(p):
							filepaths.append(p)
			else:
				paths = []
		engine = Engine(paths, filepaths, self.view)
		thread = Thread(engine, self.render)
		thread.start()

	def render(self, results, time, count):
		self.view.run_command('todo_review_render', {
			"results": results,
			"time": time,
			"count": count,
			"args": self.args
		})

class TodoReviewRender(sublime_plugin.TextCommand):
	def run(self, edit, results, time, count, args):
		global gResults
		self.args = args
		self.edit = edit
		self.time = time
		self.count = count
		gResults = results
		self.results = results
		self.sorted = self.sort()
		self.rview = self.get_view()
		self.draw_header()
		self.draw_results()
		self.window.focus_view(self.rview)
		self.args['settings'] = settings.proj
		self.rview.settings().set('review_args', self.args)

	def sort(self):
		self.largest = 0
		for item in self.results:
			self.largest = max(len(item['filename']), self.largest)
		self.largest = min(self.largest, settings.get('render_maxspaces', 50)) + 6

		sortingTimeliness = {}
		sortingTimeliness['Now'] = 1
		sortingTimeliness['Important'] = 2
		sortingTimeliness['Someday'] = 3
		sortingTimeliness['Future'] = 4
		sortingPattern = settings.get('patterns_weight', {})

		self.showtimelinessfirst = settings.get('show_timeliness_first', True)
		if self.showtimelinessfirst:
			key = lambda m: (str(sortingTimeliness.get(m['timelinessgroup'], 9)), str(sortingPattern.get(m['patt'].upper(), m['patt'])), m['timeliness'], m['priority']) #changed by JN
		else:
			key = lambda m: (str(sortingPattern.get(m['patt'].upper(), m['patt'])), str(sortingTimeliness.get(m['timelinessgroup'], 9)), m['timeliness'], m['priority']) #changed by JN
		results = sorted(self.results, key=key)
		return results

	def get_view(self):
		self.window = sublime.active_window()
		for view in self.window.views():
			if view.settings().get('todo_results', False):
				view.erase(self.edit, sublime.Region(0, view.size()))
				return view
		view = self.window.new_file()
		view.set_name('TodoReview')
		view.set_scratch(True)
		view.settings().set('todo_results', True)
		if sys.version_info < (3,0,0):
			view.set_syntax_file('Packages/TodoReview/TodoReview.hidden-tmLanguage')
		else:
			view.assign_syntax('Packages/TodoReview/TodoReview.hidden-tmLanguage')
		view.settings().set('line_padding_bottom', 2)
		view.settings().set('line_padding_top', 2)
		view.settings().set('word_wrap', False)
		view.settings().set('command_mode', True)
		return view

	def draw_header(self):
		forms = settings.get('render_header_format', '%d - %c files in %t secs')
		datestr = settings.get('render_header_date', '%A %m/%d/%y at %I:%M%p')
		if not forms:
			forms = '%d - %c files in %t secs'
		if not datestr:
			datestr = '%A %m/%d/%y at %I:%M%p'
		if len(forms) == 0:
			return
		date = datetime.datetime.now().strftime(datestr)
		res = '// '
		res += forms \
			.replace('%d', date) \
			.replace('%t', str(self.time)) \
			.replace('%c', str(self.count))
		res += '\n'
		self.rview.insert(self.edit, self.rview.size(), res)

	#changes by JN
	def draw_results(self):
		data = [x[:] for x in [[]] * 2]
		if self.showtimelinessfirst:
			keyfunc_01 = lambda m: m['timelinessgroup']
			keyfunc_02 = lambda m: m['patt']
		else:
			keyfunc_01 = lambda m: m['patt']
			keyfunc_02 = lambda m: m['timelinessgroup']

		self.setPaddingLenNumber(keyfunc_01, keyfunc_02)
		self.setShowGroupHeading(keyfunc_01, keyfunc_02)
		for key_01, items_01 in itertools.groupby(self.sorted, key=keyfunc_01):
			groupList_01 = list(items_01)
			if self.showgroupheading_01:
				res = '\n## %t (%n)\n' \
					.replace('%t', key_01.upper()) \
					.replace('%n', str(len(groupList_01)))
				self.rview.insert(self.edit, self.rview.size(), res)

			for key_02, items_02 in itertools.groupby(groupList_01, key=keyfunc_02):
				groupList_02 = list(items_02)
				if self.showgroupheading_02:
					res = '### %t (%n)\n' \
						.replace('%t', key_02.upper()) \
						.replace('%n', str(len(groupList_02)))
					self.rview.insert(self.edit, self.rview.size(), res)
				self.draw_results_add_items(data, groupList_02)
		
		self.rview.add_regions('results', data[0], '')
		d = dict(('{0},{1}'.format(k.a, k.b), v) for k, v in zip(data[0], data[1]))
		self.rview.settings().set('review_results', d)

	def draw_results_add_items(self, data, itemsList):
		for idx, item in enumerate(itemsList, 1):
			res = '%i %f%n\n' \
				.replace('%i', str(idx).rjust(self.paddinglennr)) \
				.replace('%f', self.draw_file(item).ljust(self.largest)) \
				.replace('%n', item['note'])
			start = self.rview.size()
			self.rview.insert(self.edit, start, res)
			region = sublime.Region(start, self.rview.size())
			data[0].append(region)
			data[1].append(item)

	def draw_file(self, item):
		filename = item['filename']
		namelength =  len(filename)
		overlength = namelength - self.largest
		if overlength >= 0:
			filename_splitted = filename.split(':')
			filename = filename_splitted[0]
			newnamelength = namelength - overlength - 4 - len(filename_splitted[1])
			filename = filename[0:newnamelength] + '..:' + filename_splitted[1]
		return filename

	def setPaddingLenNumber(self, keyfunc_01, keyfunc_02):
		maxLenList = 0
		for key_01, items_01 in itertools.groupby(self.sorted, key=keyfunc_01):
			groupList_01 = list(items_01)
			for key_02, items_02 in itertools.groupby(groupList_01, key=keyfunc_02):
				groupList_02 = list(items_02)
				maxLenList = max(maxLenList, len(groupList_02))
		maxLenList = max(1, maxLenList)
		self.paddinglennr = int(math.log10(maxLenList))+1

	def setShowGroupHeading(self, keyfunc_01, keyfunc_02):
		unique_01 = []
		unique_02 = []
		for key_01, items_01 in itertools.groupby(self.sorted, key=keyfunc_01):
			if key_01 not in unique_01: unique_01.append(key_01)
			groupList_01 = list(items_01)
			for key_02, items_02 in itertools.groupby(groupList_01, key=keyfunc_02):
				if key_02 not in unique_02: unique_02.append(key_02)
		if len(unique_01) > 1: self.showgroupheading_01 = True 
		else: self.showgroupheading_01 = False
		if len(unique_02) > 1: self.showgroupheading_02 = True
		else: self.showgroupheading_02 = False


class TodoReviewResults(sublime_plugin.TextCommand):
	def run(self, edit, **args):
		self.settings = self.view.settings()
		if not self.settings.get('review_results'):
			return
		if args.get('open'):
			window = self.view.window()
			index = int(self.settings.get('selected_result', -1))
			result = self.view.get_regions('results')[index]
			coords = '{0},{1}'.format(result.a, result.b)
			i = self.settings.get('review_results')[coords]
			p = "%f:%l".replace('%f', i['file']).replace('%l', str(i['line']))
			view = window.open_file(p, sublime.ENCODED_POSITION)
			window.focus_view(view)
			return
		if args.get('refresh'):
			args = self.settings.get('review_args')
			self.view.run_command('todo_review', args)
			self.settings.erase('selected_result')
			return
		if args.get('direction'):
			d = args.get('direction')
			results = self.view.get_regions('results')
			if not results:
				return
			start_arr = {
				'down': -1,
				'up': 0,
				'down_skip': -1,
				'up_skip': 0
			}
			dir_arr = {
				'down': 1,
				'up': -1,
				'down_skip': settings.get('navigation_forward_skip', 10),
				'up_skip': settings.get('navigation_backward_skip', 10) * -1
			}
			sel = int(self.settings.get('selected_result', start_arr[d]))
			sel = sel + dir_arr[d]
			if sel == -1:
				target = results[len(results) - 1]
				sel = len(results) - 1
			if sel < 0:
				target = results[0]
				sel = 0
			if sel >= len(results):
				target = results[0]
				sel = 0
			target = results[sel]
			self.settings.set('selected_result', sel)
			region = target.cover(target)
			self.view.add_regions('selection', [region], 'selected', 'dot')
			self.view.show(sublime.Region(region.a, region.a + 5))
			return
