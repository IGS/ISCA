#!/usr/bin/env python3

"""
This script parses through the output directories of threaded_alignment.py
to extract the best alignment for each assembled sequence. Note the 'priority' 
parameter which prefers that isolate set which was used to map from via GMAP. 
When the desired reference priority is not the best hit, brief stats on what %ID 
it was capable of reaching for that locus compared to the best hit are presented.

The ids_v_cov.tsv file consists of the best hits for each assembled locus. 
The columns are as follows (tab-separated):
    %ID coverage(reference/assembled) length reference path_to_best_alignment

    Input:
        1. Path to *map.tsv output from format_for_assembly.py or assembly_verdict.py
        2. Number of cores to use
        3. Path to the the directory preceding all the alignment directories 
        (e.g. for "/path/to/ref123" put "/path/to" as the input)
        4. Name of ids_v_cov.tsv output file
        5. Optional prefix for prioritizing one isolate over the others
        6. Either "yes" or "no" for whether to report stats of only the best alignment or all alignments
        7. Either "SPAdes" or "HGA". Determines how many assembled sequences are aligned to

    Output:
        1. A file which relates the %ID found when aligning the reference and
        the assembled sequence. If HGA is used, has an additional column which
        tells the %ID found just with respect to the reference and ignores any
        over-assembled internal regions of the newly assembled sequence

    Usage:
        threaded_assess_alignment.py --assmb_map /path/to/format_for_assembly.tsv \
         --align_path /path/to/alignments --ivc_outfile /path/to/output_dir --priority 3D7
    Author: 
        James Matsumura
"""

import re,argparse,os,collections,tempfile
import multiprocessing as mp
from Bio import AlignIO

def main():

    parser = argparse.ArgumentParser(description='Script to assess EMBOSS Needle alignments, follows global_alignment.py.')
    parser.add_argument('--assmb_map', '-am', type=str, required=True, help='Path to *map.tsv output from format_for_assembly.py or assembly_verdict.py.')
    parser.add_argument('--cpus', '-c', type=int, required=True, help='Number of cores to use.')
    parser.add_argument('--align_path', '-ap', type=str, required=True, help='Path to the the directory preceding all the alignment directories (e.g. for "/path/to/ref123" put "/path/to" as the input).')
    parser.add_argument('--ivc_outfile', '-io', type=str, required=True, help='Name of ids_v_cov.tsv output file.')
    parser.add_argument('--priority', '-p', type=str, required=False, default="", help='Optional prefix for prioritizing one isolate over the others.')
    parser.add_argument('--best_only', '-bo', type=str, required=True, help='Either "yes" or "no" for whether to report stats of only the best alignment or all alignments.')
    parser.add_argument('--assmb_type', '-at', type=str, required=True, help='Either "SPAdes" or "HGA". Determines how many assembled sequences are aligned to.')
    args = parser.parse_args()

    # ensure that multiprocessing module doesn't use NFS
    tempfile.tempdir = '/tmp'

    # Set up the multiprocessing manager, pool, and queue
    manager = mp.Manager()
    q = manager.Queue()
    pool = mp.Pool(args.cpus + 1)
    pool.apply_async(listener, (q,args.ivc_outfile))
    jobs = []

    # Need to iterate over the map generated from SPAdes step.
    with open(args.assmb_map,'r') as loc_map:
        for line in loc_map:
            line = line.rstrip()
            ele = line.split('\t')
            locus = ele[0]

            algn_dir = "{0}/{1}".format(args.align_path,locus)

            if args.assmb_type == "SPAdes":
                jobs.append(pool.apply_async(spades_worker, (algn_dir,locus,args.priority,args.best_only,q)))
            elif args.assmb_type == "HGA":
                jobs.append(pool.apply_async(scaffold_worker, (algn_dir,locus,args.priority,args.best_only,q)))

    # Get all the returns from the apply_async function.
    for job in jobs:
        job.get()
    
    q.put('stop') # should be no more messages
    pool.close() #  Tell the queue it's done getting new jobs
    pool.join() # Make sure these new jobs are all finished
    manager.shutdown() # Clean up / close files + sockets

# This is the worker that each CPU will process asynchronously
# Arguments:
# algn_dir = the locus that SPAdes attempted to assemble
# locus = particular locus being assessed right now
# priority = if provided, same as args.priority
# best_only = "yes" or "no" for whether or not to report just the best or all alignments
# queue = queue used to send writes to the outfile
def spades_worker(algn_dir,locus,priority,best_only,queue):
    isos,scores,ids,files,cov,length,ref_len = ([] for i in range(7)) # reinitialize for every locus

    # If the minimum threshold is set high enough, it is possible for
    # no alignments to have been performed. Print to STDOUT in case
    # this does happen. 
    aligned = False
    # Found the alignment directory for this locus, now iterate over 
    # the final alignments and pull the best score.
    for file in os.listdir(algn_dir):
        a,b = ("" for i in range(2)) # store lengths of the trimmed alignments

        if file.endswith(".trimmed_align.txt"):

            # If we know which reference we want to assemble, skip all other files. 
            if priority != "" and not file.startswith(priority):
                continue

            aligned = True 
            
            isolate = file.split('.')[0] # grab the reference group
            full_path = "{0}/{1}".format(algn_dir,file)

            # Extract the sequence lengths to establish a ratio of
            # potential coverage. >1 means reference is longer than
            # assembled seq and <1 means the assembled seq is longer.
            alignment = AlignIO.read(full_path,'emboss')
            for sequence in alignment:
                if a == "":
                    a = str(sequence.seq)
                else:
                    b = str(sequence.seq)
                

            if a != "" and b!= "":
                ref_align_len = find_ref_len(a,b)
                a = a.replace('-','')
                b = b.replace('-','')

            stats = parse_alignment(full_path)

            # Seems getting max from a list is faster than dict
            isos.append(isolate)
            scores.append(float(stats['score']))
            ids.append(stats['id'])
            cov.append(len(a)/len(b))
            length.append(len(b))
            ref_len.append(ref_align_len)
            files.append(full_path)

    # If no trimmed_align.txt files found, no alignments were performed
    # even though contigs were present.
    if aligned == False:
        #print("The locus {0} could assemble but none of the contigs passed the minimum threshold chosen when running global_alignment.py".format(locus))
        return

    if best_only == 'yes':
        best = ids.index(max(ids))

        # This block is not needed for the current set of test cases but likely
        # will be needed in the future. 
        # Make sure a tie goes to the prioritized isolate.
        #if priority != "":
        #    m = max(ids)
        #    x = [i for i, j in enumerate(ids) if j == m]
        #    if len(x) > 1: # only a concern in the case of a tie
        #        for i in x:
        #            if isos[i] == priority:
        #                best = i

        best_iso = isos[best]
        best_id = ids[best]
        best_cov = cov[best]
        best_len = length[best]
        best_ref_len = ref_len[best]
        best_file = files[best]

        queue.put("{0}\t{1}\t{2}\t{3}\t{4}\t{5}\n".format(best_id,best_cov,best_len,best_iso,best_ref_len,best_file))
    
    elif best_only == 'no':
        for x in range(0,len(files)):
            queue.put("{0}\t{1}\t{2}\t{3}\t{4}\t{5}\n".format(ids[x],cov[x],length[x],isos[x],ref_len[x],files[x]))

    # This block is not needed for the current set of test cases but likely
    # will be needed in the future. 
    #if priority != "":
        # If the best hit was not the prioritized isolate, then print to STDOUT
        # what the best value was for the priority as well as the actual best.
    #    if best_iso != priority:
    #        prioritized_indexes = [i for i,j in enumerate(isos) if j == priority]
    #        prioritized_ids = [ids[i] for i in prioritized_indexes]
            # Make sure the prioritized isolate has an alignment. 
    #        prioritized_best_id = 0
    #        if len(prioritized_ids) > 0:
    #            prioritized_best_id = max(prioritized_ids)
    #        print("{0}\t{1}\t{2}\t{3}\t{4}\t{5:.2f}".format(locus,best_iso,best_id,priority,prioritized_best_id,best_id-prioritized_best_id))

# This is the worker that each CPU will process asynchronously
# 
# This differs from the SPAdes aligner in that it also calculates
# "exact alignment" where it finds what would be the aligned 
# identity if gaps were ignored. 
#
# Arguments:
# algn_dir = the locus that HGA+SB attempted to assemble
# locus = particular locus being assessed right now
# priority = if provided, same as args.priority
# best_only = "yes" or "no" for whether or not to report just the best or all alignments
# queue = queue used to send writes to the outfile
def scaffold_worker(algn_dir,locus,priority,best_only,queue):
    isos,scores,ids,files,cov,length,ref_len,nogap_id = ([] for i in range(8)) # reinitialize for every locus

    # If the minimum threshold is set high enough, it is possible for
    # no alignments to have been performed. Print to STDOUT in case
    # this does happen. 
    aligned = False
    # Found the alignment directory for this locus, now iterate over 
    # the final alignments and pull the best score.
    for file in os.listdir(algn_dir):
        a,b = ("" for i in range(2)) # store lengths of the trimmed alignments

        if 'Scaffold' in file and file.endswith(".trimmed_align.txt"):

            # If we know which reference we want to assemble, skip all other files. 
            if priority != "" and not file.startswith(priority):
                continue

            aligned = True 
            
            isolate = file.split('.')[0] # grab the reference group
            full_path = "{0}/{1}".format(algn_dir,file)

            # Make sure the file is actually populated and EMBOSS didn't fail
            if os.stat(full_path).st_size == 0:
                #print("{0} is empty.".format(full_path))
                continue


            # Extract the sequence lengths to establish a ratio of
            # potential coverage. >1 means reference is longer than
            # assembled seq and <1 means the assembled seq is longer.
            alignment = AlignIO.read(full_path,'emboss')
            for sequence in alignment:
                if a == "":
                    a = str(sequence.seq)
                else:
                    b = str(sequence.seq)
               

                if a != "" and b!= "":
                    ref_align_len = find_ref_len(a,b)
                    # Check how many bases of A are covered by B with exact 
                    # matches and output this percentage. Ignore gaps.
                    nogap_id.append(calculate_exact_alignment(a,b)) 

                    # Just get the length of the sequences to calculate coverage.
                    # Note that the presence of spacers or extraneous repeats 
                    # can have a significant impact on shifting the coverage 
                    # ratio to find the assembly as much longer. 
                    a = a.replace('-','')
                    b = b.replace('-','')

            stats = parse_alignment(full_path)

            # Seems getting max from a list is faster than dict
            isos.append(isolate)
            scores.append(float(stats['score']))
            ids.append(stats['id'])
            cov.append(len(a)/len(b))
            length.append(len(b))
            ref_len.append(ref_align_len)
            files.append(full_path)

    # If no trimmed_align.txt files found, no alignments were performed
    # even though contigs were present.
    if aligned == False:
        #print("The locus {0} could build a scaffold but failed to find an alignment.".format(locus))
        return

    if best_only == 'yes':
        # We want to find the best ID regardless of GAPs (meaning how many of the
        # reference bases can be covered).
        best = nogap_id.index(max(nogap_id))
        
        # This block is not needed for the current set of test cases but likely
        # will be needed in the future. 
        # Make sure a tie goes to the prioritized isolate.
        #if priority != "":
        #    m = max(ids)
        #    x = [i for i, j in enumerate(ids) if j == m]
        #    if len(x) > 1: # only a concern in the case of a tie
        #        for i in x:
        #            if isos[i] == priority:
        #                best = i

        best_iso = isos[best]
        best_id = ids[best]
        best_cov = cov[best]
        best_len = length[best]
        best_ref_len = ref_len[best]
        best_file = files[best]
        best_nogap_id = nogap_id[best]

        queue.put("{0}\t{1}\t{2}\t{3}\t{4}\t{5}\t{6}\n".format(best_id,best_cov,best_len,best_iso,best_ref_len,best_file,best_nogap_id))

    elif best_only == 'no':
        for x in range(0,len(files)):
            queue.put("{0}\t{1}\t{2}\t{3}\t{4}\t{5}\t{6}\n".format(ids[x],cov[x],length[x],isos[x],ref_len[x],files[x],nogap_id[x]))

    # This block is not needed for the current set of test cases but likely
    # will be needed in the future. 
    #if priority != "":
        # If the best hit was not the prioritized isolate, then print to STDOUT
        # what the best value was for the priority as well as the actual best.
    #    if best_iso != priority:
    #        prioritized_indexes = [i for i,j in enumerate(isos) if j == priority]
    #        prioritized_ids = [ids[i] for i in prioritized_indexes]
            # Make sure the prioritized isolate has an alignment. 
    #        prioritized_best_id = 0
    #        if len(prioritized_ids) > 0:
    #            prioritized_best_id = max(prioritized_ids)
    #        print("{0}\t{1}\t{2}\t{3}\t{4}\t{5:.2f}".format(locus,best_iso,best_id,priority,prioritized_best_id,best_id-prioritized_best_id))


# This will act as the sole writer to the output file. This way there is no 
# concern with locks and what not. This listens for messages and writes to
# the final map file. 
# Arguments:
# queue = queue used to communicate what should be written out
# out_file = location and name of the file to write out
def listener(queue,out_file):

    while 1:
        msg = queue.get()
        if msg == 'stop':
            break
        with open(out_file,'a') as out:
            out.write(str(msg))
            out.flush()

# Function to parse over the output of EMBOSS's Needle program and extract the
# score of the alignment.
# Argument:
# infile = *.trimmed_align.txt file generated from a Needle alignment. 
def parse_alignment(infile):

    stats = {'score':0,'id':0}

    with open(infile,'r') as alignment:
        for line in alignment:
            if line.startswith('# Score:'):
                stats['score'] = re.search(r'#\sScore:\s(.*)$',line).group(1) 
            elif line.startswith('# Identity:'):
                stats['id'] = re.search(r'#\sIdentity:\s+\d+/\d+\s\(\s?(\d+\.\d+)%\)$',line).group(1)
                stats['id'] = float(stats['id'])
            elif line.startswith('a.trimmed'): # reached actual alignment, no need
                break

    return stats

# Function to check how many bases from the reference are mapping to the 
# assembled sequence. 
def calculate_exact_alignment(aseq,bseq):

    total,perfect_match = (0 for i in range(2))

    for a_base,b_base in zip(aseq,bseq):
        # If it's not a gap for A, check if it aligns perfectly to B
        if a_base != "-": # only care about what exists in the reference
            if a_base == b_base: # if match, note it as such
                perfect_match += 1
                total += 1
            else: # not a reference gap and not a match
                total += 1

    return "{0:.2f}".format(perfect_match/total*100)


# Finding the length of reference sequence in alignment
def find_ref_len(a,b):
    a_align_seq = a
    if a[0] != "-" and b[0] == "-":
        bstrip1 = b.lstrip('-')
        ltrim = len(b) - len(bstrip1)
        a_align_seq = a[ltrim:]
    if a[-1] != "-" and b[-1] == "-":
        bstrip2 = b.rstrip('-')
        rtrim = (len(b) - len(bstrip2)) * -1
        a_align_seq = a_align_seq[:rtrim]
    a_align_seq = a_align_seq.replace('-', '')
    ref_align_len = len(a_align_seq)

    return ref_align_len

if __name__ == '__main__':
    main()
