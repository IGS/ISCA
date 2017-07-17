# targeted_assembly
A pipeline to perform targeted assembly of individual loci given WGS reads, reference genome assemblies, and a primary reference annotation (GFF3)

## Dependencies:
- Python 3.5
  * [Biopython](https://pypi.python.org/pypi/biopython/1.66)
    * [EMBOSS](http://emboss.open-bio.org/)
  * [pysam](https://pypi.python.org/pypi/pysam)
- Python 2.7
  * Primarily needed for the externally developed scripts (HGA and Scaffold Builder)
  * [cwlref-runner](https://pypi.python.org/pypi/cwlref-runner)
  * [pyyaml](https://pypi.python.org/pypi/PyYAML)
- [GSNAP](http://research-pub.gene.com/gmap/)
- [SMALT](http://www.sanger.ac.uk/science/tools/smalt-0)
- [SPAdes](http://bioinf.spbau.ru/spades)
- [Velvet](https://www.ebi.ac.uk/~zerbino/velvet/)
- [MUMmer](http://mummer.sourceforge.net/manual/)
- Python Scripts
  * [Hierarchical Genome Assembly Tool](https://github.com/jmatsumura/Hierarchical-Genome-Assembly-HGA)
    * [Original for reference](https://github.com/aalokaily/Hierarchical-Genome-Assembly-HGA)
  * [Scaffold Builder](https://github.com/jmatsumura/Scaffold_builder)
    * [Original for reference](https://github.com/metageni/Scaffold_builder))

## Invoking a CWL workflow
```
cwl-runner <cwl tool/workflow script> <input parameter yml/json>
```
The first parameter is a valid cwl tool or workflow script.  These have the extension __.cwl__.

The second parameter is a YAML or JSON file consisting of input parameters for the CWL script. YAML examples are provided and are listed with the extension __.yml__.

## Complete steps:
1. Map an annotated reference genome to other assembled genomes
  * `GMAP`
2. Build a map for the alleles extracted from GFF3
  * `extract_alleles.py` 
3. Extract sequences for all references given the previous scripts output
  * `extract_sequences.py` 
4. GSNAP/SMALT
  * Build index
  * align
  * optional, but can compress SAM to BAM here
5. Analyze BAM to map reads to refs and vice-versa 
  * `analyze_bam.py`
6. Assign all the reads to their own directories for each reference
  * `fastq_reads_to_fastq_alleles.py`
7. Rename all the directories to format for running SPAdes on the grid 
  * `format_for_assembly.py`
8. SPAdes
  * http://spades.bioinf.spbau.ru/release3.5.0/manual.html
9. Run alignment 
  * `threaded_alignment.py`
10. Run assessment to isolate the best assemblies and overall stats
  * `threaded_assess_alignment.py`
11. If there are any remaining loci that could not assemble at a desired minimum threshold, can isolate these reference sequences to another round of the pipeline and use a different aligner/sensitivity. Note that using this step will essentially format the data similar to the end of step 3. 
  * `assembly_verdict.py`
12. Assemble those that SPAdes could not using HGA+Scaffold Builder.
  * `wrap_HGA.py`
  * `wrap_Scaffold_Builder.py`
13. Rerun alignment using these new assemblies.
  * `threaded_alignment.py`
14. Assess these new assemblies.
  * `threaded_assess_alignment.py`
15. Build a dataset for those that cannot align
  * `assembly_verdict.py`
16. Repeat steps 4-15 using the SMALT aligner
