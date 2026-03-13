import glob, os, time
from datetime import date
from collections import defaultdict
from tqdm import tqdm

import unicodedata
import re
import numpy as np
import matplotlib.pyplot as plt

import polars as pl
try :
    import fastexcel
except :
    print( 'WARNING: fastexcel not found.' )
    print( 'fastexcel is required to read .xslx tables.' )
    print( 'pip install fastexcel or use your venv manager.' )
try :
    import xlsxwriter
except :
    print( 'WARNING: xlsxwriter not found.' )
    print( 'xlsxwriter is required to write .xslx tables.' )
    print( 'pip install xlsxwriter or use your venv manager.' )


class BiodiversityDataset :

    def __init__(self,
                 oecd_data_filename='OECD.DCD.FSD,DSD_RIOMRKR@DF_RIOMARKERS,1.4+DAC_EC..1000..2.10...Q._T...csv',
                 oecd_data_filename_list=None,
                 oecd_data_separator=',',
                 oecd_infer_schema_length=10_000,
                 oecd_data_dtypes={'crsid':str},
                 oecd_title_colname='projecttitle',
                 oecd_desc_colname='longdescription',
                 keyword_data_filename='keywords_list.txt',
                 climate_instead=False,
                 init_only=False, debug=1 ):

        if not oecd_data_filename is None :
            print( 'will read oecd data from file:\n'+ oecd_data_filename )
            self.oecd_data_filename = oecd_data_filename
            basename = self.oecd_data_filename.rstrip(' data.text').replace(' ', '_')
        elif not oecd_data_filename_list is None :
            print( 'will read oecd data from file list:' )
            for filename in oecd_data_filename_list :
                print( filename )
            basename = filename.split(' 20')[0]+'_allyears'

        self.climate_instead = climate_instead

        self.today = today = date.today().strftime("%Y%m%d")
        if self.climate_instead :
            basename = f'./climate_output_{today}/' + basename.split('/')[-1]
            basename = basename + '_climate'
        else :
            basename = f'./biodiversity_output_{today}/' + basename.split('/')[-1]
            basename = basename + '_biodiversity'
        self.basename = basename
        outdir = os.path.abspath(os.path.dirname(basename))
        if not os.path.exists(outdir):
            os.makedirs(outdir)
        print( 'output to be written as:' )
        print( basename + '...' )

        print( 'will read keyword data from file:\n' + keyword_data_filename )
        self.keyword_data_filename = keyword_data_filename

        self.debug = debug
        if self.debug > 0: print( 'debug =', self.debug )

        if oecd_data_filename_list is None :
            self.data = self.read_oecd_data(
                filename=self.oecd_data_filename,
                separator=oecd_data_separator,
                infer_schema_length=oecd_infer_schema_length,
                schema_overrides=oecd_data_dtypes,
            )
        else :
            # read all tables
            data = [ self.read_oecd_data(
                filename=oecd_data_filename,
                separator=oecd_data_separator,
                infer_schema_length=oecd_infer_schema_length,
                schema_overrides=oecd_data_dtypes, )
                for oecd_data_filename in oecd_data_filename_list ]
            # check consistent datatypes
            for col in data[0].columns :
                dtypes = [d[col].dtype for d in data]
                okay = all([d == dtypes[0] for d in dtypes])
                if not okay:
                    for d in data :
                        d = d.with_columns(pl.col(col).cast(pl.Int64))
                    check = [d[col].dtype for d in data]
                    check = all([d == check[0] for d in check])
                    print( check )

            print( 'combining data from', len(data), 'blocks' )
            self.data = pl.concat(data)
            print( len(self.data), 'rows in combined dataset' )

        if init_only :
            print( 'init_only = TRUE' )
            return

        self.read_keyword_data(
            keyword_column_name=keyword_column_name
        )

        self.prepare_oecd_data(
            oecd_title_colname=oecd_title_colname,
            oecd_desc_colname=oecd_desc_colname,
        )

        self.do_keyword_search()

        self.write_results(
            oecd_title_colname=oecd_title_colname,
            oecd_desc_colname=oecd_desc_colname,
        )

    def read_oecd_data(self, filename, **kwargs):

        print( f'reading {filename} ...', end=' ', flush=True )
        starttime = time.time()
        data = pl.read_csv(filename, **kwargs )

        print( f'done! ({time.time() - starttime:.1f} s)' )

        if self.debug > 3:
            print( 'column names are:' )
            for i, col in enumerate( data.columns ): print( i, col )
        if self.debug:
            print( f'read {len(data)} lines from oecd data file.' )

        if self.climate_instead :
            print( 'filtering on climateAdaptaton or climateMitigation >= 1...', end=' ', flush=True )
            # for earliest data dtype guess for climateAdaptation is string
            for col in 'climateMitigation climateAdaptation'.split() :
                if data[col].dtype == pl.String :
                    data = data.with_columns(pl.col(col).cast(pl.Int64))
            data = data.filter( ( pl.col('climateMitigation') >= 1 )
                                 | ( pl.col('climateAdaptation') >= 1 ) )
            print( 'done!' )

            pass
        else :
            print( 'filtering on biodiversity >= 1...', end=' ', flush=True )
            data = data.filter( pl.col('biodiversity') >= 1 )
            print( 'done!' )

        if self.debug:
            print( f'have {len(data)} filtered lines from oecd data file.' )

        # self.data = data
        return data


    def prepare_oecd_data(self,
                          oecd_title_colname,
                          oecd_desc_colname):

        print( 'preparing oecd data now...', end=' ', flush=True )
        starttime = time.time()

        title_desc = []

        for (title, desc) in zip(
                self.data[oecd_title_colname],
                self.data[oecd_desc_colname] ) :

            if title is None : title = ''
            if desc is None : desc = ''

            text = '\n'.join(( title, desc ))
            text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
            title_desc.append( text )

        self.title_desc_list = title_desc
        print( f'done. ({(time.time()-starttime):.1f} s)' )

    def read_keyword_data(self, keyword_column_name):
        import time

        print('reading keyword data now...', end=' ', flush=True)
        starttime = time.time()
        # data = pl.read_excel(self.keyword_data_filename)
        with open( self.keyword_data_filename, 'r' ) as f :
            lines = f.read().split('\n')
        print(f'done! ({time.time() - starttime:.1f} s)')
        self.keyword_data = lines

        if self.debug:
            print(f'read {len(lines)} lines from oecd data file.')

        if self.debug > 9:
            print( 'removing null keywords.' )

        # if self.debug :
        #     print( 'sorting keywords alphabetically.' )
        # data = data.sort( keyword_column_name )

        # unpack specifications to get a list of distinct keywords
        keyword_list = []
        for entry in lines :
            if entry is None : continue

            # decode to remove any special (non-ascii) characters
            entry = unicodedata.normalize('NFKD', entry
                                          ).encode('ascii', 'ignore'
                                                   ).decode()

            # most specifications are single words
            if not "'" in entry :
                elements = [ word for word in entry.split(', ') ]

            # a few are 'longer phrases', 'comma separated'
            else :
                elements = re.findall("'([^']*)'", entry)

            # build these into a long list to be parsed futher in a moment
            keyword_list += elements
            if self.debug > 8 :
                print( entry, elements )

        # quick check to element any null entries
        keyword_list = [ kw for kw in keyword_list if len( kw ) > 0 ]

        # now formulate the regex for each search in a dict
        keyword_dict = {}
        for entry in keyword_list :

            if (not '/' in entry) and (not "," in entry) :
                # no 'or' options; these are easy
                kw = entry.lstrip(' *').split('*')[0].replace(' ','_')
                regex = r'\b' + entry.lstrip(' ').replace('*', r'\w*') + r'\b'
                if self.debug > 7 :
                    print(f'"{kw}" : "{regex}"')

            elif (not "," in entry) :
                # one or more 'or' options to collect as (a|b|c)
                kw = entry.lstrip('*').split('/')[0].replace('*','').replace(' ', '_')
                regex = '|'.join([ f'{bit}' for bit in entry.split('/') ])
                regex = r'\b(' + regex.replace('*', r'\w*') + r')\b'
                regex = regex.replace(r'\w* ', r'\w*\b')
                if self.debug > 7:
                    print(f'"{kw}" : "{regex}"')

            else:
                kw = entry.replace(',', '').replace(' ', '_')
                regex = r'\b(' + entry.replace(', ', r',?\s*' ) + r')\b'
                if self.debug > 7:
                    print(f'"{kw}" : "{regex}"')

            if '.' in kw :
                kw = kw.replace(' ', '.')

            if kw in keyword_dict.keys():
                if keyword_dict[kw] != regex :
                    print( f'WARNING: conflicting keyword definitions: "{kw}"' )
                    print( kw, f"{regex}" )
                    print( kw, keyword_dict[kw] )
                    sys.exit()
                else :
                    print( f'WARNING: duplicate keyword definition: "{kw}"' )

            keyword_dict[ kw ] = regex
        self.keyword_dict = keyword_dict

        if self.debug > 3 :
            print( 'will search for the following keywords:' )
            for kw, regex in keyword_dict.items() :
                print(f'"{kw}" : "{regex}"')

            print( list( self.keyword_dict.keys() ) )

    def do_keyword_search(self):

        results = defaultdict(list)
        self.keyword_counts = {}
        self.match_tables = {}

        total_matches, keywords_matched = 0, 0

        print( 'starting keyword search now.' )

        keyword_match_list_filename = f'{self.basename}_keyword_match_list_{self.today}.txt'

        with open( keyword_match_list_filename, 'w' ) as outfile :
            pass

        for (i, (keyword, regex)) in enumerate(
                self.keyword_dict.items() ): # self.keyword_list:

            print( f'searching for keyword ({i}/{len(self.keyword_dict)}): {keyword}' )

            case_sensitive = not ( keyword == keyword.lower() )
            if case_sensitive:
                pass
            else :
                regex = r'(?i)' + regex
            if self.debug > 3 :
                print( f'regex is: "{regex}"' )

            # create an empty list to hold the counts for each row
            counts_list = []
            # create an empty defalutdict to track unique matches for each keyword
            matches_dict = defaultdict(lambda: 0)

            for text in self.title_desc_list :
                match_list = re.findall(regex, text)

                # record the number of matches for this keyword/row
                counts_list.append(len(match_list))

                for word in match_list:
                    if not case_sensitive:
                        matches_dict[ word.lower() ] += 1
                    # otherwise keep track of the original case
                    else :
                        matches_dict[ word ] += 1
            # the matches_dict tracks the number of matches for each unique matched word

            counts_list = np.array(counts_list)
            self.keyword_counts[keyword] = counts_list

            total_matches += counts_list
            keywords_matched += np.clip( counts_list, 0, 1 )

            total = np.sum(counts_list > 0)
            if self.debug > 3 :
                print( total, 'projects matched' )

            try :
                words = np.array([ key for key in matches_dict.keys() ])
                counts = np.array([ matches_dict[word] for word in words ])
                sorder = np.argsort( -counts )
                words, counts = words[sorder], counts[sorder]
            except :
                print( 'badness!')
                print( matches_dict )

            matches_dict = { w:c for (w,c) in zip(words, counts) }

            with open(keyword_match_list_filename, 'a') as outfile:

                print( f'# {keyword}: "{regex}" ({total} projects; {np.sum(counts_list)} matches)' )
                print( f'# {keyword}: "{regex}" ({total} projects; {np.sum(counts_list)} matches)', file=outfile )

                for (word,count) in matches_dict.items():
                    print( f'{word} ({count})' )
                    print( f'{word} ({count})', file=outfile )

            self.match_tables[ keyword ] = matches_dict

        self.keyword_counts['keywords_matched'] = keywords_matched
        self.keyword_counts[ 'total_matches' ] = total_matches

        for key, counts in self.keyword_counts.items():
            if np.sum( counts ) == 0 :
                continue
            if key == 'keywords_matched' or key == 'total_matches' :
                self.data.insert_column(
                    len(self.data.columns), pl.Series(key, counts) )
            else :
                self.data.insert_column(
                    len(self.data.columns), pl.Series(f'{key}_counts', counts) )


    def write_results(self, oecd_title_colname='projecttitle',
                 oecd_desc_colname='longdescription',
                      ):

        today = self.today

        towrite = self.data
        with open( f'{self.basename}_full_output_{today}.csv', 'w' ) as f :
            towrite.write_csv( f )

        towrite = self.data.filter( self.data['total_matches'] > 0 )
        with open( f'{self.basename}_matched_output_{today}.csv', 'w' ) as f :
            towrite.write_csv( f )

        towrite = self.data.drop( oecd_desc_colname )
        with open( f'{self.basename}_nodesc_output_{today}.csv', 'w' ) as f :
            towrite.write_csv( f )


if __name__ == '__main__':

    oecd_data_filename_list = np.sort(glob.glob('oecd_oda_data/Rio*txt'))[::-1]
    oecd_data_separator = '|'
    oecd_data_dtypes = {'crsid': str,
                        'climateAdaptation': int,
                        'Programme Based Approaches': int}
    keyword_data_filename = 'keywords_list.txt'
    for climate_instead in [ False, True ] :

        # do the combined dataset in its entirety
        data = BiodiversityDataset(
            oecd_data_filename=None,
            oecd_data_filename_list=oecd_data_filename_list,
            oecd_data_separator=oecd_data_separator,
            oecd_data_dtypes=oecd_data_dtypes,
            keyword_data_filename=keyword_data_filename,
            climate_instead=climate_instead,
            debug=1, init_only=False)

        # do each set of years one by one
        for oecd_data_filename in oecd_data_filename_list:

            data = BiodiversityDataset(
                oecd_data_filename=oecd_data_filename,
                oecd_data_separator=oecd_data_separator,
                oecd_data_dtypes=oecd_data_dtypes,
                keyword_data_filename=keyword_data_filename,
                climate_instead=climate_instead,
                debug=1, init_only=False)

