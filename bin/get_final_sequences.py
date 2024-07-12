#!/usr/bin/env python3

"""
A script that follows threaded_assess_alignment.py and pulls the best 
assembled sequence into a single FASTA file. Note that the best %ID 
achieved when aligning to the reference will be included in the FASTA 
header along with the length of each assembled sequence and the length
of reference sequence that aligned with assembled sequence.

    Input:
        1. Path to ids_v_cov.tsv output from threaded_assess_alignment.py
        2. Cutoff for pulling a sequence or not. Can set to 0 to get anything
        3. Get sequences by loci, alleles/exons, or CDS (could also be exons 
           if extracted at ea_map step), choose either "l", "ae", or "cds"
        4. Path to where all the alignments were performed
        5. Path to ea_map.tsv output from extract_alleles.py
        6. Name of an outfile to populate with the final assemblies
        7. Path to where the unbuffered FASTA from extract_sequences.py is 
        8. Optional minimum length ratio of an assembled sequence as cutoff 
           for pulling a sequence or not. Default 0.5.

    Output:
        1. An outfile containing all the best assembled sequences 

    Usage:
        get_final_sequences.py --align_path /path/to/alignments --ivc ids_v_cov.tsv --outfile out.fsa --threshold 90 --ea_map /path/to/ea_map.tsv 

    Author: 
        James Matsumura
"""

import argparse,collections,sys,os
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
from collections import defaultdict

def main():

    parser = argparse.ArgumentParser(description='Script to generate basic stats from the output of threaded_assess_alignment.py.')
    parser.add_argument('--ivc', '-i', type=str, required=True, help='Path to ids_v_cov.tsv output from threaded_assess_alignment.py.')
    parser.add_argument('--threshold', '-t', type=int, default=0, required=False, help='Cutoff for pulling a sequence or not. Can set to 0 to get anything.')
    parser.add_argument('--groupby', '-g', type=str, required=True, help='Get sequences by loci, alleles/exons, or CDS (could also be exons if extracted at ea_map step), choose either "l", "ae", or "cds".')
    parser.add_argument('--align_path', '-ap', type=str, required=True, help='Path to where all the alignments are.')
    parser.add_argument('--outfile', '-o', type=str, required=True, help='Name of an outfile.')
    parser.add_argument('--ea_map', '-eam', type=str, required=True, help='Path to ea_map.tsv output from extract_alleles.py.')
    parser.add_argument('--original_fsa', '-of', type=str, required=True, help='Path to where the unbuffered FASTA from extract_sequences.py is.')
    parser.add_argument('--min_align_len', '-minl', type=float, required=False, default=0.5, help='Optional minimum length ratio of an assembled sequence as cutoff for pulling a sequence or not. Default 0.5.')
    args = parser.parse_args()

    best_id,cds_map = (defaultdict(list) for i in range(2)) 
    cds_lengths = {} # count how many exons in a CDS from ea_map
    seq_dict = SeqIO.to_dict(SeqIO.parse(args.original_fsa,"fasta"))
    min_len = args.min_align_len

    with open(args.ivc,'r') as infile:
        for line in infile:
            line = line.rstrip()
            elements = line.split('\t')

            entity = ""
            if args.groupby != 'l':
                entity = os.path.basename(elements[5]).split('.WITH')[0]
                #Check ids_v_cov.tsv to find ref.geneID; test the following line
                #ref_seq = entity
            else:
                entity = os.path.basename(elements[5]).split('.')[1]
                ref_seq = os.path.basename(elements[5]).split('.WITH')[0]

            # Modify the path to where this file is found; needs some extra 
            # handholding to work both with/without CWL
            base_dir = args.align_path
            split_point = os.path.basename(base_dir)
            tmp_path = elements[5].split(split_point)[1]
            file_path = "{0}/{1}".format(base_dir,tmp_path)
            unbuffered_ref_seq = seq_dict[ref_seq]
            
            # Sort the %ID into bins
            id = 0.0
            if len(elements) == 6:
                id = float(elements[0])
            else:
                id = float(elements[6])

            # Check the length and cov index positions for cds, 
            # alleles/exons and other groupby methods
            length = int(elements[2])
            cov = float(elements[1])
            ref_len = int(elements[4])
            
            if ref_len < int(len(unbuffered_ref_seq)*min_len):
                continue

            if int(id) < args.threshold:
                continue

            if entity in best_id:
                if id > best_id[entity][0]:
                    best_id[entity][0] = id
                    best_id[entity][1] = file_path
                    best_id[entity][2] = length
                    best_id[entity][3] = cov
                    best_id[entity][4] = ref_seq
                    best_id[entity][5] = ref_len
            else:
                best_id[entity].append(id)
                best_id[entity].append(file_path)
                best_id[entity].append(length)
                best_id[entity].append(cov)
                best_id[entity].append(ref_seq)
                best_id[entity].append(ref_len)

    if args.groupby == 'cds':
        for k,v in best_id.items():
            parent = get_exon_parent(k)
            cds_map[parent].append(v)

        with open(args.ea_map,'r') as infile:
            for line in infile:
                elements = line.split('\t')
                for x in range(1,len(elements)):
                    parent = get_exon_parent(elements[x].split('|')[-1]).strip()
                    if parent in cds_lengths:
                        cds_lengths[parent] += 1
                    else:
                        cds_lengths[parent] = 1

        # sort the keys to output exons in order and make joining for CDS easy
        delete_us = set()
        for k in cds_map:
            if len(cds_map[k]) != cds_lengths[k]:
                print("CDS for {0} is incomplete, will not be present in FASTA file".format(k))
                delete_us.add(k)

        # Check if this section fails by introduction of lengths and cov in cds_map values
            elif len(cds_map[k]) > 1: # only sort if multiple exons
                if 'mrna' in cds_map[k][0][1]:
                    cds_map[k].sort(key = lambda x: int(x[1].rsplit('exon',1)[1].split('.')[0]))   
                else:
                    cds_map[k].sort(key = lambda x: int(x[1].split('-')[1].split('.')[0]))

        for incomplete in delete_us:
            del cds_map[incomplete]

    final_sequences = []

    if args.groupby != 'cds': # treat individual loci/alleles/exons differently than CDS
        for k,v in best_id.items():
            new_id = "assembled_{0}".format(k)
            ref_len = v[5]
            seq = seq_dict[v[4]] 
            ref_len_percent = round((ref_len/len(seq)*100), 2)
            file = v[1].replace('trimmed_align.txt','b.fsa')

            record = SeqIO.read(file, "fasta")
            record.id = new_id
            record.description = 'ID_to_ref={0} len={1} ref_len_percent={2}'.format(v[0],v[2],str(ref_len_percent))
            record.name = ''
            if '.r.trimmed' in v[1]:
                tmp_seq = Seq(str(record.seq))
                record.seq = tmp_seq.reverse_complement() 

            final_sequences.append(record)

    else:
        for k,v in cds_map.items():
            sequence = ''
            for exon in v:
                file = exon[1].replace('trimmed_align.txt','b.fsa')
                record = SeqIO.read(file, "fasta")
                if '.r.trimmed' in exon[1]:
                    tmp_seq = Seq(str(record.seq))
                    sequence += str(tmp_seq.reverse_complement() )

                else:
                    sequence += str(record.seq)

            # Add len and ref_len in record description
            record = SeqRecord(Seq(sequence),id="cds_{0}".format(k),description='')
           
            final_sequences.append(record)

    SeqIO.write(final_sequences, args.outfile, 'fasta')
            
def get_exon_parent(exon):
    if '-' in exon or 'exon_' in exon:
        return exon.split('-')[0]
    else:
        return exon.rsplit('.',1)[0]

if __name__ == '__main__':
    main()
