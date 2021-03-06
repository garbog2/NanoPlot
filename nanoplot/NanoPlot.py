#! /usr/bin/env python
# wdecoster

'''
The main purpose of this script is to create plots for long read sequencing data.
Input data can be given as one or multiple of:
-compressed, standard or streamed fastq file
-compressed, standard or streamed fastq file, with
 additional information added by albacore or MinKNOW
-a bam file
-a summary file generated by albacore
'''


from argparse import ArgumentParser
from os import path
import logging
import nanomath
import numpy as np
from scipy import stats
import nanoplot.utils as utils
from nanoget import get_input
from nanoplot.filteroptions import filter_and_transform_data
from .version import __version__
import nanoplotter
import pickle
import sys


def main():
    '''
    Organization function
    -setups logging
    -gets inputdata
    -calls plotting function
    '''
    args = get_args()
    try:
        utils.make_output_dir(args.outdir)
        utils.init_logs(args)
        args.format = nanoplotter.check_valid_format(args.format)
        settings = vars(args)
        settings["path"] = path.join(args.outdir, args.prefix)
        sources = {
            "fastq": args.fastq,
            "bam": args.bam,
            "cram": args.cram,
            "fastq_rich": args.fastq_rich,
            "fastq_minimal": args.fastq_minimal,
            "summary": args.summary,
            "fasta": args.fasta,
            "ubam": args.ubam,
        }

        if args.pickle:
            datadf = pickle.load(open(args.pickle, 'rb'))
        else:
            datadf = get_input(
                source=[n for n, s in sources.items() if s][0],
                files=[f for f in sources.values() if f][0],
                threads=args.threads,
                readtype=args.readtype,
                combine="simple",
                barcoded=args.barcoded)
        if args.store:
            pickle.dump(
                obj=datadf,
                file=open(settings["path"] + "NanoPlot-data.pickle", 'wb'))
        if args.raw:
            datadf.to_csv("NanoPlot-data.tsv.gz", sep="\t", index=False, compression="gzip")

        settings["statsfile"] = [make_stats(datadf, settings, suffix="")]
        datadf, settings = filter_and_transform_data(datadf, settings)
        if settings["filtered"]:  # Bool set when filter was applied in filter_and_transform_data()
            settings["statsfile"].append(make_stats(datadf, settings, suffix="_post_filtering"))

        if args.barcoded:
            barcodes = list(datadf["barcode"].unique())
            plots = []
            for barc in barcodes:
                logging.info("Processing {}".format(barc))
                settings["path"] = path.join(args.outdir, args.prefix + barc + "_")
                dfbarc = datadf[datadf["barcode"] == barc]
                if len(dfbarc) > 5:
                    settings["title"] = barc
                    plots.extend(
                        make_plots(dfbarc, settings)
                    )
                else:
                    sys.stderr.write("Found barcode {} less than 5x, ignoring...\n".format(barc))
                    logging.info("Found barcode {} less than 5 times, ignoring".format(barc))
        else:
            plots = make_plots(datadf, settings)
        make_report(plots, settings)
        logging.info("Finished!")
    except Exception as e:
        logging.error(e, exc_info=True)
        print("\n\n\nIf you read this then NanoPlot has crashed :-(")
        print("Please try updating NanoPlot and see if that helps...\n")
        print("If not, please report this issue at https://github.com/wdecoster/NanoPlot/issues")
        print("If you could include the log file that would be really helpful.")
        print("Thanks!\n\n\n")
        raise


def get_args():
    epilog = """EXAMPLES:
    Nanoplot --summary sequencing_summary.txt --loglength -o summary-plots-log-transformed
    NanoPlot -t 2 --fastq reads1.fastq.gz reads2.fastq.gz --maxlength 40000 --plots hex dot
    NanoPlot --color yellow --bam alignment1.bam alignment2.bam alignment3.bam --downsample 10000
    """
    parser = ArgumentParser(
        description="Creates various plots for long read sequencing data.".upper(),
        epilog=epilog,
        formatter_class=utils.custom_formatter,
        add_help=False)
    general = parser.add_argument_group(
        title='General options')
    general.add_argument("-h", "--help",
                         action="help",
                         help="show the help and exit")
    general.add_argument("-v", "--version",
                         help="Print version and exit.",
                         action="version",
                         version='NanoPlot {}'.format(__version__))
    general.add_argument("-t", "--threads",
                         help="Set the allowed number of threads to be used by the script",
                         default=4,
                         type=int)
    general.add_argument("--verbose",
                         help="Write log messages also to terminal.",
                         action="store_true")
    general.add_argument("--store",
                         help="Store the extracted data in a pickle file for future plotting.",
                         action="store_true")
    general.add_argument("--raw",
                         help="Store the extracted data in tab separated file.",
                         action="store_true")
    general.add_argument("-o", "--outdir",
                         help="Specify directory in which output has to be created.",
                         default=".")
    general.add_argument("-p", "--prefix",
                         help="Specify an optional prefix to be used for the output files.",
                         default="",
                         type=str)
    filtering = parser.add_argument_group(
        title='Options for filtering or transforming input prior to plotting')
    filtering.add_argument("--maxlength",
                           help="Drop reads longer than length specified.",
                           type=int,
                           metavar='N')
    filtering.add_argument("--minlength",
                           help="Drop reads shorter than length specified.",
                           type=int,
                           metavar='N')
    filtering.add_argument("--drop_outliers",
                           help="Drop outlier reads with extreme long length.",
                           action="store_true")
    filtering.add_argument("--downsample",
                           help="Reduce dataset to N reads by random sampling.",
                           type=int,
                           metavar='N')
    filtering.add_argument("--loglength",
                           help="Logarithmic scaling of lengths in plots.",
                           action="store_true")
    filtering.add_argument("--percentqual",
                           help="Use qualities as theoretical percent identities.",
                           action="store_true")
    filtering.add_argument("--alength",
                           help="Use aligned read lengths rather than sequenced length (bam mode)",
                           action="store_true")
    filtering.add_argument("--minqual",
                           help="Drop reads with an average quality lower than specified.",
                           type=int,
                           metavar='N')
    filtering.add_argument("--runtime_until",
                           help="Only take the N first hours of a run",
                           type=int,
                           metavar='N')
    filtering.add_argument("--readtype",
                           help="Which read type to extract information about from summary. \
                                 Options are 1D, 2D, 1D2",
                           default="1D",
                           choices=['1D', '2D', '1D2'])
    filtering.add_argument("--barcoded",
                           help="Use if you want to split the summary file by barcode",
                           action="store_true")
    visual = parser.add_argument_group(
        title='Options for customizing the plots created')
    visual.add_argument("-c", "--color",
                        help="Specify a color for the plots, must be a valid matplotlib color",
                        default="#4CB391")
    visual.add_argument("-f", "--format",
                        help="Specify the output format of the plots.",
                        default="png",
                        type=str,
                        choices=['eps', 'jpeg', 'jpg', 'pdf', 'pgf', 'png', 'ps',
                                 'raw', 'rgba', 'svg', 'svgz', 'tif', 'tiff'])
    visual.add_argument("--plots",
                        help="Specify which bivariate plots have to be made.",
                        default=['kde', 'dot'],
                        type=str,
                        nargs='*',
                        choices=['kde', 'hex', 'dot', 'pauvre'])
    visual.add_argument("--listcolors",
                        help="List the colors which are available for plotting and exit.",
                        action=utils.Action_Print_Colors,
                        default=False)
    visual.add_argument("--no-N50",
                        help="Hide the N50 mark in the read length histogram",
                        action="store_true")
    visual.add_argument("--N50",
                        help="Show the N50 mark in the read length histogram",
                        action="store_true",
                        default=False)
    visual.add_argument("--title",
                        help="Add a title to all plots, requires quoting if using spaces",
                        type=str,
                        default=None)
    visual.add_argument("--font_scale",
                        help="Scale the font of the plots by a factor",
                        type=float,
                        default=1)
    visual.add_argument("--dpi",
                        help="Set the dpi for saving images",
                        type=int,
                        default=100)
    target = parser.add_argument_group(
        title="Input data sources, one of these is required.")
    mtarget = target.add_mutually_exclusive_group(
        required=True)
    mtarget.add_argument("--fastq",
                         help="Data is in one or more default fastq file(s).",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--fasta",
                         help="Data is in one or more fasta file(s).",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--fastq_rich",
                         help="Data is in one or more fastq file(s) generated by albacore, \
                               MinKNOW or guppy with additional information \
                               concerning channel and time.",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--fastq_minimal",
                         help="Data is in one or more fastq file(s) generated by albacore, \
                               MinKNOW or guppy with additional information concerning channel \
                               and time. Is extracted swiftly without elaborate checks.",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--summary",
                         help="Data is in one or more summary file(s) generated by albacore \
                               or guppy.",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--bam",
                         help="Data is in one or more sorted bam file(s).",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--ubam",
                         help="Data is in one or more unmapped bam file(s).",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--cram",
                         help="Data is in one or more sorted cram file(s).",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--pickle",
                         help="Data is a pickle file stored earlier.",
                         metavar="pickle")
    args = parser.parse_args()
    if args.listcolors:
        utils.list_colors()
    if args.no_N50:
        sys.stderr.write('DeprecationWarning: --no-N50 is currently the default setting.\n')
        sys.stderr.write('The argument is thus unnecessary but kept for backwards compatibility.')
    return args


def make_stats(datadf, settings, suffix):
    statsfile = settings["path"] + "NanoStats" + suffix + ".txt"
    nanomath.write_stats(
        datadfs=[datadf],
        outputfile=statsfile)
    logging.info("Calculated statistics")
    if settings["barcoded"]:
        barcodes = list(datadf["barcode"].unique())
        statsfile = settings["path"] + "NanoStats_barcoded.txt"
        nanomath.write_stats(
            datadfs=[datadf[datadf["barcode"] == b] for b in barcodes],
            outputfile=statsfile,
            names=barcodes)
    return statsfile


def make_plots(datadf, settings):
    '''
    Call plotting functions from nanoplotter
    settings["lengths_pointer"] is a column in the DataFrame specifying which lengths to use
    '''
    plot_settings = dict(font_scale=settings["font_scale"])
    nanoplotter.plot_settings(plot_settings, dpi=settings["dpi"])
    color = nanoplotter.check_valid_color(settings["color"])
    plotdict = {type: settings["plots"].count(type) for type in ["kde", "hex", "dot", 'pauvre']}
    plots = []
    if settings["N50"]:
        n50 = nanomath.get_N50(np.sort(datadf["lengths"]))
    else:
        n50 = None
    plots.extend(
        nanoplotter.length_plots(
            array=datadf[datadf["length_filter"]]["lengths"],
            name="Read length",
            path=settings["path"],
            n50=n50,
            color=color,
            figformat=settings["format"],
            title=settings["title"])
    )
    logging.info("Created length plots")
    if "quals" in datadf:
        plots.extend(
            nanoplotter.scatter(
                x=datadf[datadf["length_filter"]][settings["lengths_pointer"]],
                y=datadf[datadf["length_filter"]]["quals"],
                names=['Read lengths', 'Average read quality'],
                path=settings["path"] + "LengthvsQualityScatterPlot",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                log=settings["logBool"],
                title=settings["title"],
                plot_settings=plot_settings)
        )
        logging.info("Created LengthvsQual plot")
    if "channelIDs" in datadf:
        plots.extend(
            nanoplotter.spatial_heatmap(
                array=datadf["channelIDs"],
                title=settings["title"],
                path=settings["path"] + "ActivityMap_ReadsPerChannel",
                color="Greens",
                figformat=settings["format"])
        )
        logging.info("Created spatialheatmap for succesfull basecalls.")
    if "start_time" in datadf:
        plots.extend(
            nanoplotter.time_plots(
                df=datadf,
                path=settings["path"],
                color=color,
                figformat=settings["format"],
                title=settings["title"],
                log_length=settings["logBool"],
                plot_settings=plot_settings)
        )
        logging.info("Created timeplots.")
    if "aligned_lengths" in datadf and "lengths" in datadf:
        plots.extend(
            nanoplotter.scatter(
                x=datadf[datadf["length_filter"]]["aligned_lengths"],
                y=datadf[datadf["length_filter"]]["lengths"],
                names=["Aligned read lengths", "Sequenced read length"],
                path=settings["path"] + "AlignedReadlengthvsSequencedReadLength",
                figformat=settings["format"],
                plots=plotdict,
                color=color,
                title=settings["title"],
                plot_settings=plot_settings)
        )
        logging.info("Created AlignedLength vs Length plot.")
    if "mapQ" in datadf and "quals" in datadf:
        plots.extend(
            nanoplotter.scatter(
                x=datadf["mapQ"],
                y=datadf["quals"],
                names=["Read mapping quality", "Average basecall quality"],
                path=settings["path"] + "MappingQualityvsAverageBaseQuality",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                title=settings["title"],
                plot_settings=plot_settings)
        )
        logging.info("Created MapQvsBaseQ plot.")
        plots.extend(
            nanoplotter.scatter(
                x=datadf[datadf["length_filter"]][settings["lengths_pointer"]],
                y=datadf[datadf["length_filter"]]["mapQ"],
                names=["Read length", "Read mapping quality"],
                path=settings["path"] + "MappingQualityvsReadLength",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                log=settings["logBool"],
                title=settings["title"],
                plot_settings=plot_settings)
        )
        logging.info("Created Mapping quality vs read length plot.")
    if "percentIdentity" in datadf:
        minPID = np.percentile(datadf["percentIdentity"], 1)
        if "aligned_quals" in datadf:
            plots.extend(
                nanoplotter.scatter(
                    x=datadf["percentIdentity"],
                    y=datadf["aligned_quals"],
                    names=["Percent identity", "Average Base Quality"],
                    path=settings["path"] + "PercentIdentityvsAverageBaseQuality",
                    color=color,
                    figformat=settings["format"],
                    plots=plotdict,
                    stat=stats.pearsonr,
                    minvalx=minPID,
                    title=settings["title"],
                    plot_settings=plot_settings)
            )
            logging.info("Created Percent ID vs Base quality plot.")
        plots.extend(
            nanoplotter.scatter(
                x=datadf[datadf["length_filter"]][settings["lengths_pointer"]],
                y=datadf[datadf["length_filter"]]["percentIdentity"],
                names=["Aligned read length", "Percent identity"],
                path=settings["path"] + "PercentIdentityvsAlignedReadLength",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                stat=stats.pearsonr,
                log=settings["logBool"],
                minvaly=minPID,
                title=settings["title"],
                plot_settings=plot_settings)
        )
        logging.info("Created Percent ID vs Length plot")
    return plots


def make_report(plots, settings):
    '''
    Creates a fat html report based on the previously created files
    plots is a list of Plot objects defined by a path and title
    statsfile is the file to which the stats have been saved,
    which is parsed to a table (rather dodgy)
    '''
    logging.info("Writing html report.")
    html_content = ['<body>']

    # Hyperlink Table of Contents panel
    html_content.append('<div class="panel panelC">')
    if settings["filtered"]:
        html_content.append(
            '<p><strong><a href="#stats0">Summary Statistics prior to filtering</a></strong></p>')
        html_content.append(
            '<p><strong><a href="#stats1">Summary Statistics after filtering</a></strong></p>')
    else:
        html_content.append(
            '<p><strong><a href="#stats0">Summary Statistics</a></strong></p>')
    html_content.append('<p><strong><a href="#plots">Plots</a></strong></p>')
    html_content.extend(['<p style="margin-left:20px"><a href="#' +
                         p.title.replace(' ', '_') + '">' + p.title + '</a></p>' for p in plots])
    html_content.append('</div>')

    # The report itself: stats
    html_content.append('<div class="panel panelM"> <h1>NanoPlot report</h1>')
    if settings["filtered"]:
        html_content.append('<h2 id="stats0">Summary statistics prior to filtering</h2>')
        html_content.append(utils.stats2html(settings["statsfile"][0]))
        html_content.append('<h2 id="stats1">Summary statistics after filtering</h2>')
        html_content.append(utils.stats2html(settings["statsfile"][1]))
    else:
        html_content.append('<h2 id="stats0">Summary statistics</h2>')
        html_content.append(utils.stats2html(settings["statsfile"][0]))

    # The report itself: plots
    html_content.append('<h2 id="plots">Plots</h2>')
    for plot in plots:
        html_content.append('\n<h3 id="' + plot.title.replace(' ', '_') + '">' +
                            plot.title + '</h3>\n' + plot.encode())
        html_content.append('\n<br>\n<br>\n<br>\n<br>')
    html_body = '\n'.join(html_content) + '</div></body></html>'
    html_str = utils.html_head + html_body
    htmlreport = settings["path"] + "NanoPlot-report.html"
    with open(htmlreport, "w") as html_file:
        html_file.write(html_str)
    return htmlreport


if __name__ == "__main__":
    main()
