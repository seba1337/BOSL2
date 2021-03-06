#!/usr/bin/env python3

from __future__ import print_function

import os
import re
import sys
import math
import random
import hashlib
import filecmp
import dbm.gnu
import os.path
import platform
import argparse
import subprocess

from PIL import Image, ImageChops


if platform.system() == "Darwin":
    OPENSCAD = "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"
    GIT = "git"
else:
    OPENSCAD = "openscad"
    GIT = "git"


def image_compare(file1, file2):
    img1 = Image.open(file1)
    img2 = Image.open(file2)
    if img1.size != img2.size or img1.getbands() != img2.getbands():
        return False
    diff = ImageChops.difference(img1, img2).histogram()
    sq = (value * (i % 256) ** 2 for i, value in enumerate(diff))
    sum_squares = sum(sq)
    rms = math.sqrt(sum_squares / float(img1.size[0] * img1.size[1]))
    return rms<2


def image_resize(infile, outfile, newsize=(320,240)):
    im = Image.open(infile)
    im.thumbnail(newsize, Image.ANTIALIAS)
    im.save(outfile)


def make_animated_gif(imgfiles, outfile, size):
    imgs = []
    for file in imgfiles:
        img = Image.open(file)
        img.thumbnail(size, Image.ANTIALIAS)
        imgs.append(img)
    imgs[0].save(
        outfile,
        save_all=True,
        append_images=imgs[1:],
        duration=250,
        loop=0
    )

def git_checkout(filename):
    # Pull previous committed image from git, if it exists.
    gitcmd = [GIT, "checkout", filename]
    p = subprocess.Popen(gitcmd, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
    err = p.stdout.read()


def run_openscad_script(libfile, infile, imgfile, imgsize=(320,240), eye=None, show_edges=False, render=False, test_only=False):
    if test_only:
        scadcmd = [
            OPENSCAD,
            "-o", "foo.term",
            "--hardwarnings"
        ]
    else:
        scadcmd = [
            OPENSCAD,
            "-o", imgfile,
            "--imgsize={},{}".format(imgsize[0]*2, imgsize[1]*2),
            "--hardwarnings",
            "--projection=o",
            "--autocenter",
            "--viewall"
        ]
        if eye is not None:
            scadcmd.extend(["--camera", eye+",0,0,0"])
        if show_edges:
            scadcmd.extend(["--view=axes,scales,edges"])
        else:
            scadcmd.extend(["--view=axes,scales"])
    if render:  # Force render
        scadcmd.extend(["--render", ""])
    scadcmd.append(infile)
    with open(infile, "r") as f:
        script = "".join(f.readlines());
    p = subprocess.Popen(scadcmd, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    (stdoutdata, stderrdata) = p.communicate(None)
    res = p.returncode
    if test_only and os.path.isfile("foo.term"):
        os.unlink("foo.term")
    if res != 0 or b"ERROR:" in stderrdata or b"TRACE:" in stderrdata:
        print("\n\n{}".format(stderrdata.decode('utf-8')))
        print("////////////////////////////////////////////////////")
        print("// {}: {} for {}".format(libfile, infile, imgfile))
        print("////////////////////////////////////////////////////")
        print(script)
        print("////////////////////////////////////////////////////")
        print("")
        with open("FAILED.scad", "w") as f:
            print("////////////////////////////////////////////////////", file=f)
            print("// {}: {} for {}".format(libfile, infile, imgfile), file=f)
            print("////////////////////////////////////////////////////", file=f)
            print(script, file=f)
            print("////////////////////////////////////////////////////", file=f)
            print("", file=f)
        sys.exit(-1)
    return imgfile


class ImageProcessing(object):
    def __init__(self):
        self.examples = []
        self.imgroot = ""
        self.keep_scripts = False
        self.force = False
        self.test_only = False

    def set_keep_scripts(self, x):
        self.keep_scripts = x

    def add_image(self, libfile, imgfile, code, extype):
        self.examples.append((libfile, imgfile, code, extype))

    def process_examples(self, imgroot, force=False, test_only=False):
        self.imgroot = imgroot
        self.force = force
        self.test_only = test_only
        self.hashes = {}
        with dbm.gnu.open("examples_hashes.gdbm", "c") as db:
            for libfile, imgfile, code, extype in self.examples:
                self.gen_example_image(db, libfile, imgfile, code, extype)
            for key, hash in self.hashes.items():
                db[key] = hash

    def gen_example_image(self, db, libfile, imgfile, code, extype):
        if extype == "NORENDER":
            return

        print("  {}".format(imgfile), end='')
        sys.stdout.flush()

        test_only = self.test_only
        scriptfile = "tmp_{0}.scad".format(imgfile.replace(".", "_"))
        targimgfile = self.imgroot + imgfile
        newimgfile = self.imgroot + "_new_" + imgfile

        # Pull previous committed image from git, if it exists.
        git_checkout(targimgfile)

        m = hashlib.sha256()
        m.update(extype.encode("utf8"))
        for line in code:
            m.update(line.encode("utf8"))
        hash = m.digest()
        key = "{0} - {1}".format(libfile, imgfile)
        if key in db and db[key] == hash and not self.force:
            print("")
            return

        script = ""
        for line in code:
            script += line+"\n"

        with open(scriptfile, "w") as f:
            f.write(script)

        if "Huge" in extype:
            imgsize = (800, 600)
        elif "Big" in extype:
            imgsize = (640, 480)
        elif "Med" in extype or "distribute" in script or "show_anchors" in script:
            imgsize = (480, 360)
        else:  # Small
            imgsize = (320, 240)

        show_edges = "Edges" in extype
        render = "FR" in extype

        tmpimgs = []
        if "Spin" in extype and not test_only:
            for ang in range(0,359,10):
                tmpimgfile = "{0}tmp_{2}_{1}.png".format(self.imgroot, ang, imgfile.replace(".", "_"))
                arad = ang * math.pi / 180;
                eye = "{0},{1},{2}".format(
                    500*math.cos(arad),
                    500*math.sin(arad),
                    500 if "Flat" in extype else 500*math.sin(arad)
                )
                run_openscad_script(
                    libfile, scriptfile, tmpimgfile,
                    imgsize=(imgsize[0]*2,imgsize[1]*2),
                    eye=eye,
                    show_edges=show_edges,
                    render=render,
                    test_only=test_only
                )
                tmpimgs.append(tmpimgfile)
                print(".", end='')
                sys.stdout.flush()
        else:
            tmpimgfile = self.imgroot + "tmp_" + imgfile
            eye = "0,0,500" if "2D" in extype else None
            run_openscad_script(
                libfile, scriptfile, tmpimgfile,
                imgsize=(imgsize[0]*2,imgsize[1]*2),
                eye=eye,
                show_edges=show_edges,
                render=render,
                test_only=test_only
            )
            tmpimgs.append(tmpimgfile)

        if not self.keep_scripts:
            os.unlink(scriptfile)

        if not test_only:
            if len(tmpimgs) == 1:
                image_resize(tmpimgfile, newimgfile, imgsize)
                os.unlink(tmpimgs.pop(0))
            else:
                make_animated_gif(tmpimgs, newimgfile, size=imgsize)
                for tmpimg in tmpimgs:
                    os.unlink(tmpimg)

        print("")

        if not test_only:
            # Time to compare image.
            if not os.path.isfile(targimgfile):
                print("    NEW IMAGE\n")
                os.rename(newimgfile, targimgfile)
            else:
                if targimgfile.endswith(".gif"):
                    issame = filecmp.cmp(targimgfile, newimgfile, shallow=False)
                else:
                    issame  = image_compare(targimgfile, newimgfile);
                if issame:
                    os.unlink(newimgfile)
                else:
                    print("    UPDATED IMAGE\n")
                    os.unlink(targimgfile)
                    os.rename(newimgfile, targimgfile)
            self.hashes[key] = hash


imgprc = ImageProcessing()


def get_header_link(name):
    refpat = re.compile("[^a-z0-9_ -]")
    return refpat.sub("", name.lower()).replace(" ", "-")


def toc_entry(name, indent, count=None):
    lname = "{0}{1}".format(
        ("%d. " % count) if count else "",
        name
    )
    ref = get_header_link(lname)
    if name.endswith( (")", "}", "]") ):
        name = "`" + name.replace("\\", "") + "`"
    return "{0}{1} [{2}](#{3})".format(
        indent,
        ("%d." % count) if count else "-",
        name,
        ref
    )


def mkdn_esc(txt):
    out = ""
    quotpat = re.compile(r'([^`]*)(`[^`]*`)(.*$)');
    while txt:
        m = quotpat.match(txt)
        if m:
            out += m.group(1).replace(r'_', r'\_').replace(r'&',r'&amp;').replace(r'<', r'&lt;').replace(r'>',r'&gt;')
            out += m.group(2)
            txt = m.group(3)
        else:
            out += txt.replace(r'_', r'\_').replace(r'&',r'&amp;').replace(r'<', r'&lt;').replace(r'>',r'&gt;')
            txt = ""
    return out


def get_comment_block(lines, prefix, blanks=1):
    out = []
    blankcnt = 0
    indent = 0
    while lines:
        if not lines[0].startswith(prefix+" "):
            break
        line = lines.pop(0)[len(prefix):]
        if not indent:
            while line.startswith(" "):
                line = line[1:]
                indent += 1
        else:
            line = line[indent:]
        if line == "":
            blankcnt += 1
            if blankcnt >= blanks:
                break
        else:
            blankcnt = 0
        if line.rstrip() == '.':
            line = "\n"
        out.append(line.rstrip())
    return (lines, out)


class LeafNode(object):
    def __init__(self):
        self.name = ""
        self.leaftype = ""
        self.status = ""
        self.topics = []
        self.usages = []
        self.description = []
        self.figures = []
        self.returns = []
        self.customs = []
        self.arguments = []
        self.named_arguments = []
        self.anchors = []
        self.side_effects = []
        self.examples = []

    @classmethod
    def match_line(cls, line, prefix):
        if line.startswith(prefix + "Constant: "):
            return True
        if line.startswith(prefix + "Function: "):
            return True
        if line.startswith(prefix + "Function&Module: "):
            return True
        if line.startswith(prefix + "Module: "):
            return True
        return False

    def add_figure(self, title, code, figtype):
        self.figures.append((title, code, figtype))

    def add_example(self, title, code, extype):
        self.examples.append((title, code, extype))

    def parse_lines(self, lines, prefix):
        blankcnt = 0
        expat = re.compile(r"^(Examples?)(\(([^\)]*)\))?: *(.*)$")
        figpat = re.compile(r"^(Figures?)(\(([^\)]*)\))?: *(.*)$")
        while lines:
            if prefix and not lines[0].startswith(prefix.strip()):
                break
            line = lines.pop(0).rstrip()
            if line.lstrip("/").strip() == "":
                blankcnt += 1
                if blankcnt >= 2:
                    break
                continue
            blankcnt = 0

            line = line[len(prefix):]
            if line.startswith("Constant:"):
                leaftype, title = line.split(":", 1)
                self.name = title.strip()
                self.leaftype = leaftype.strip()
                continue
            if line.startswith("Function&Module:"):
                leaftype, title = line.split(":", 1)
                self.name = title.strip()
                self.leaftype = leaftype.strip()
                continue
            if line.startswith("Function:"):
                leaftype, title = line.split(":", 1)
                self.name = title.strip()
                self.leaftype = leaftype.strip()
                continue
            if line.startswith("Module:"):
                leaftype, title = line.split(":", 1)
                self.name = title.strip()
                self.leaftype = leaftype.strip()
                continue

            if line.startswith("Status:"):
                dummy, status = line.split(":", 1)
                self.status = status.strip()
                continue
            if line.startswith("Topics:"):
                dummy, topic_line = line.split(":", 1)
                topics = []
                for topic in topic_line.split(","):
                    self.topics.append(topic.strip())
                continue
            if line.startswith("Usage:"):
                dummy, title = line.split(":", 1)
                title = title.strip()
                lines, block = get_comment_block(lines, prefix)
                if block == []:
                    print("Error: Usage header without any usage examples.")
                    print(line)
                    sys.exit(-2)
                self.usages.append([title, block])
                continue
            if line.startswith("Description:"):
                dummy, desc = line.split(":", 1)
                desc = desc.strip()
                if desc:
                    self.description.append(desc)
                lines, block = get_comment_block(lines, prefix)
                self.description.extend(block)
                continue
            if line.startswith("Returns:"):
                dummy, desc = line.split(":", 1)
                desc = desc.strip()
                if desc:
                    self.returns.append(desc)
                lines, block = get_comment_block(lines, prefix)
                self.returns.extend(block)
                continue
            if line.startswith("Custom:"):
                dummy, title = line.split(":", 1)
                title = title.strip()
                lines, block = get_comment_block(lines, prefix)
                self.customs.append( (title, block) )
                continue
            m = figpat.match(line)
            if m:  # Figure(TYPE):
                plural = m.group(1) == "Figures"
                figtype = m.group(3)
                title = m.group(4)
                lines, block = get_comment_block(lines, prefix)
                if not figtype:
                    figtype = "3D"
                if not plural:
                    self.add_figure(title, block, figtype)
                else:
                    for line in block:
                        self.add_figure("", [line], figtype)
                continue
            if line.startswith("Arguments:"):
                lines, block = get_comment_block(lines, prefix)
                named = False
                for line in block:
                    if line.strip() == "---":
                        named = True
                        continue
                    if "=" not in line:
                        print("Error in {}: Could not parse line in Argument block.  Missing '='.".format(self.name))
                        print("Line read was:")
                        print(line)
                        sys.exit(-2)
                    argname, argdesc = line.split("=", 1)
                    argname = argname.strip()
                    argdesc = argdesc.strip()
                    if named:
                        self.named_arguments.append([argname, argdesc])
                    else:
                        self.arguments.append([argname, argdesc])
                continue
            if line.startswith("Extra Anchors:") or line.startswith("Anchors:"):
                lines, block = get_comment_block(lines, prefix)
                for line in block:
                    if "=" not in line:
                        print("Error: bad anchor line:")
                        print(line)
                        sys.exit(-2)
                    anchorname, anchordesc = line.split("=", 1)
                    anchorname = anchorname.strip()
                    anchordesc = anchordesc.strip()
                    self.anchors.append([anchorname, anchordesc])
                continue
            if line.startswith("Side Effects:"):
                lines, block = get_comment_block(lines, prefix)
                self.side_effects.extend(block)
                continue

            m = expat.match(line)
            if m:  # Example(TYPE):
                plural = m.group(1) == "Examples"
                extype = m.group(3)
                title = m.group(4)
                lines, block = get_comment_block(lines, prefix)
                if not extype:
                    extype = "3D" if self.leaftype in ["Module", "Function&Module"] else "NORENDER"
                if not plural:
                    self.add_example(title=title, code=block, extype=extype)
                else:
                    for line in block:
                        self.add_example(title="", code=[line], extype=extype)
                continue

            if ":" not in line:
                print("Error in {}: Unrecognized block header.  Missing colon?".format(self.name))
            else:
                print("Error in {}: Unrecognized block header.".format(self.name))
            print("Line read was:")
            print(line)
            sys.exit(-2)

        return lines

    def gen_md(self, fileroot, imgroot, libnode, sectnode):
        out = []
        if self.name:
            out.append("### " + mkdn_esc(self.name))
            out.append("**Type:** {0}".format(mkdn_esc(self.leaftype.replace("&","/"))))
            out.append("")
        if self.status:
            out.append("**{0}**".format(mkdn_esc(self.status)))
            out.append("")
        for title, usages in self.usages:
            if not title:
                title = ""
            out.append("**Usage:** {0}".format(mkdn_esc(title)))
            for usage in usages:
                out.append("- {0}".format(mkdn_esc(usage)))
            out.append("")
        if self.description:
            out.append("**Description:**")
            for line in self.description:
                out.append(mkdn_esc(line))
            out.append("")
        fignum = 0
        for title, excode, extype in self.figures:
            fignum += 1
            extitle = "**Figure {0}:**".format(fignum)
            if title:
                extitle += " " + mkdn_esc(title)
            san_name = re.sub(r"[^A-Za-z0-9_]", "", self.name)
            imgfile = "{}_{}.{}".format(
                san_name,
                ("fig%d" % fignum),
                "gif" if "Spin" in extype else "png"
            )
            icode = []
            for line in libnode.includes:
                icode.append(line)
            for line in libnode.commoncode:
                icode.append(line)
            for line in excode:
                if line.strip().startswith("--"):
                    icode.append(line.strip()[2:])
                else:
                    icode.append(line)
            imgprc.add_image(fileroot+".scad", imgfile, icode, extype)
            out.append(extitle)
            out.append("")
            out.append(
                "![{0} Figure {1}]({2}{3})".format(
                    mkdn_esc(self.name),
                    fignum,
                    imgroot,
                    imgfile
                )
            )
            out.append("")
        if self.returns:
            out.append("**Returns:**")
            for line in self.returns:
                out.append(mkdn_esc(line))
            out.append("")
        if self.customs:
            for title, block in self.customs:
                out.append("**{}:**".format(title))
                for line in block:
                    out.append(mkdn_esc(line))
                out.append("")
        if self.arguments or self.named_arguments:
            out.append("**Arguments:**")
        if self.arguments:
            out.append('<abbr title="These args can be used by position or by name.">By&nbsp;Position</abbr> | What it does')
            out.append("---------------- | ------------------------------")
            for argname, argdesc in self.arguments:
                argname = " / ".join("`{}`".format(x.strip()) for x in argname.replace("|","/").split("/"))
                out.append(
                    "{0:15s} | {1}".format(
                        mkdn_esc(argname),
                        mkdn_esc(argdesc)
                    )
                )
            out.append("")
        if self.named_arguments:
            out.append('<abbr title="These args must be used by name, ie: name=value">By&nbsp;Name</abbr>   | What it does')
            out.append("-------------- | ------------------------------")
            for argname, argdesc in self.named_arguments:
                argname = " / ".join("`{}`".format(x.strip()) for x in argname.replace("|","/").split("/"))
                out.append(
                    "{0:15s} | {1}".format(
                        mkdn_esc(argname),
                        mkdn_esc(argdesc)
                    )
                )
            out.append("")
        if self.side_effects:
            out.append("**Side Effects:**")
            for sfx in self.side_effects:
                out.append("- " + mkdn_esc(sfx))
            out.append("")
        if self.anchors:
            out.append("Anchor Name     | Description")
            out.append("--------------- | ------------------------------")
            for anchorname, anchordesc in self.anchors:
                anchorname = " / ".join("`{}`".format(x.strip()) for x in anchorname.replace("|","/").split("/"))
                out.append(
                    "{0:15s} | {1}".format(
                        mkdn_esc(anchorname),
                        mkdn_esc(anchordesc)
                    )
                )
            out.append("")
        if self.topics:
            topics = []
            for topic in self.topics:
                topics.append("[{0}](Topics#{0})".format(mkdn_esc(topic)))
            out.append("**Related Topics:** {}".format(", ".join(topics)))
            out.append("")
        exnum = 0
        for title, excode, extype in self.examples:
            exnum += 1
            if len(self.examples) < 2:
                extitle = "**Example:**"
            else:
                extitle = "**Example {0}:**".format(exnum)
            if title:
                extitle += " " + mkdn_esc(title)
            san_name = re.sub(r"[^A-Za-z0-9_]", "", self.name)
            imgfile = "{}{}.{}".format(
                san_name,
                ("_%d" % exnum) if exnum > 1 else "",
                "gif" if "Spin" in extype else "png"
            )
            if "NORENDER" not in extype:
                icode = []
                for line in libnode.includes:
                    icode.append(line)
                for line in libnode.commoncode:
                    icode.append(line)
                for line in excode:
                    if line.strip().startswith("--"):
                        icode.append(line.strip()[2:])
                    else:
                        icode.append(line)
                imgprc.add_image(fileroot+".scad", imgfile, icode, extype)
            if "Hide" not in extype:
                out.append(extitle)
                out.append("")
                for line in libnode.includes:
                    out.append("    " + line)
                for line in excode:
                    if not line.strip().startswith("--"):
                        out.append("    " + line)
                out.append("")
                if "NORENDER" not in extype:
                    out.append(
                        "![{0} Example{1}]({2}{3})".format(
                            mkdn_esc(self.name),
                            (" %d" % exnum) if len(self.examples) > 1 else "",
                            imgroot,
                            imgfile
                        )
                    )
                    out.append("")
        out.append("---")
        out.append("")
        return out


class Section(object):
    fignum = 0
    def __init__(self):
        self.name = ""
        self.description = []
        self.leaf_nodes = []
        self.figures = []

    @classmethod
    def match_line(cls, line, prefix):
        if line.startswith(prefix + "Section: "):
            return True
        return False

    def add_figure(self, figtitle, figcode, figtype):
        self.figures.append((figtitle, figcode, figtype))

    def parse_lines(self, lines, prefix):
        line = lines.pop(0).rstrip()
        dummy, title = line.split(": ", 1)
        self.name = title.strip()
        lines, block = get_comment_block(lines, prefix, blanks=2)
        self.description.extend(block)
        blankcnt = 0
        figpat = re.compile(r"^(Figures?)(\(([^\)]*)\))?: *(.*)$")
        while lines:
            if prefix and not lines[0].startswith(prefix.strip()):
                break
            line = lines.pop(0).rstrip()
            if line.lstrip("/").strip() == "":
                blankcnt += 1
                if blankcnt >= 2:
                    break
                continue
            blankcnt = 0
            line = line[len(prefix):]
            m = figpat.match(line)
            if m:  # Figures(TYPE):
                plural = m.group(1) == "Figures"
                figtype = m.group(3)
                title = m.group(4)
                lines, block = get_comment_block(lines, prefix)
                if not figtype:
                    figtype = "3D" if self.figtype in ["Module", "Function&Module"] else "NORENDER"
                if not plural:
                    self.add_figure(title, block, figtype)
                else:
                    for line in block:
                        self.add_figure("", [line], figtype)
        return lines

    def gen_md_toc(self, count):
        indent=""
        out = []
        if self.name:
            out.append(toc_entry(self.name, indent, count=count))
            indent += "    "
        for node in self.leaf_nodes:
            out.append(toc_entry(node.name, indent))
        out.append("")
        return out

    def gen_md(self, count, fileroot, imgroot, libnode):
        out = []
        if self.name:
            out.append("# %d. %s" % (count, mkdn_esc(self.name)))
            out.append("")
        if self.description:
            in_block = False
            for line in self.description:
                if line.startswith("```"):
                    in_block = not in_block
                if in_block or line.startswith("    "):
                    out.append(line)
                else:
                    out.append(mkdn_esc(line))
            out.append("")
        for title, figcode, figtype in self.figures:
            Section.fignum += 1
            figtitle = "**Figure {0}:**".format(Section.fignum)
            if title:
                figtitle += " " + mkdn_esc(title)
            out.append(figtitle)
            out.append("")
            imgfile = "{}{}.{}".format(
                "figure",
                Section.fignum,
                "gif" if "Spin" in figtype else "png"
            )
            if figtype != "NORENDER":
                out.append(
                    "![{0} Figure {1}]({2}{3})".format(
                        mkdn_esc(self.name),
                        Section.fignum,
                        imgroot,
                        imgfile
                    )
                )
                out.append("")
                icode = []
                for line in libnode.includes:
                    icode.append(line)
                for line in libnode.commoncode:
                    icode.append(line)
                for line in figcode:
                    if line.strip().startswith("--"):
                        icode.append(line.strip()[2:])
                    else:
                        icode.append(line)
                imgprc.add_image(fileroot+".scad", imgfile, icode, figtype)
        in_block = False
        for node in self.leaf_nodes:
            out += node.gen_md(fileroot, imgroot, libnode, self)
        return out


class LibFile(object):
    def __init__(self):
        self.name = ""
        self.description = []
        self.includes = []
        self.commoncode = []
        self.sections = []
        self.deprecated_section = None

    def parse_lines(self, lines, prefix):
        currsect = None
        constpat = re.compile(r"^([A-Z_0-9][A-Z_0-9]*) *=.*  // (.*$)")
        while lines:
            while lines and prefix and not lines[0].startswith(prefix.strip()):
                line = lines.pop(0)
                m = constpat.match(line)
                if m:
                    if currsect == None:
                        currsect = Section()
                        self.sections.append(currsect)
                    node = LeafNode();
                    node.extype = "Constant"
                    node.name = m.group(1).strip()
                    node.description.append(m.group(2).strip())
                    currsect.leaf_nodes.append(node)

            # Check for LibFile header.
            if lines and lines[0].startswith(prefix + "LibFile: "):
                line = lines.pop(0).rstrip()
                dummy, title = line.split(": ", 1)
                self.name = title.strip()
                lines, block = get_comment_block(lines, prefix, blanks=2)
                self.description.extend(block)

            # Check for Includes header.
            if lines and lines[0].startswith(prefix + "Includes:"):
                lines.pop(0)
                lines, block = get_comment_block(lines, prefix)
                self.includes.extend(block)

            # Check for CommonCode header.
            if lines and lines[0].startswith(prefix + "CommonCode:"):
                lines.pop(0)
                lines, block = get_comment_block(lines, prefix)
                self.commoncode.extend(block)

            # Check for Section header.
            if lines and Section.match_line(lines[0], prefix):
                sect = Section()
                lines = sect.parse_lines(lines, prefix)
                self.sections.append(sect)
                currsect = sect

            # Check for LeafNode.
            if lines and LeafNode.match_line(lines[0], prefix):
                node = LeafNode()
                lines = node.parse_lines(lines, prefix)
                deprecated = node.status.startswith("DEPRECATED")
                if deprecated:
                    if self.deprecated_section == None:
                        self.deprecated_section = Section()
                        self.deprecated_section.name = "Deprecations"
                    sect = self.deprecated_section
                else:
                    if currsect == None:
                        currsect = Section()
                        self.sections.append(currsect)
                    sect = currsect
                sect.leaf_nodes.append(node)
            if lines:
                lines.pop(0)
        return lines

    def gen_md(self, fileroot, imgroot):
        out = []
        if self.name:
            out.append("# Library File " + mkdn_esc(self.name))
            out.append("")
        if self.description:
            in_block = False
            for line in self.description:
                if line.startswith("```"):
                    in_block = not in_block
                if in_block or line.startswith("    "):
                    out.append(line)
                else:
                    out.append(mkdn_esc(line))
            out.append("")
            in_block = False
        if self.includes:
            out.append("To use, add the following lines to the beginning of your file:")
            out.append("```openscad")
            for line in self.includes:
                out.append("    " + line)
            out.append("```")
            out.append("")
        if self.name or self.description:
            out.append("---")
            out.append("")

        if self.sections or self.deprecated_section:
            out.append("# Table of Contents")
            out.append("")
            cnt = 0
            for sect in self.sections:
                cnt += 1
                out += sect.gen_md_toc(cnt)
            if self.deprecated_section:
                cnt += 1
                out += self.deprecated_section.gen_md_toc(cnt)
            out.append("---")
            out.append("")

        cnt = 0
        for sect in self.sections:
            cnt += 1
            out += sect.gen_md(cnt, fileroot, imgroot, self)
        if self.deprecated_section:
            cnt += 1
            out += self.deprecated_section.gen_md(cnt, fileroot, imgroot, self)
        return out


def processFile(infile, outfile=None, gen_imgs=False, test_only=False, imgroot="", prefix="", force=False):
    if imgroot and not imgroot.endswith('/'):
        imgroot += "/"

    libfile = LibFile()
    with open(infile, "r") as f:
        lines = f.readlines()
        libfile.parse_lines(lines, prefix)

    if outfile == None:
        f = sys.stdout
    else:
        f = open(outfile, "w")

    fileroot = os.path.splitext(os.path.basename(infile))[0]
    outdata = libfile.gen_md(fileroot, imgroot)
    for line in outdata:
        print(line, file=f)

    if gen_imgs:
        imgprc.process_examples(imgroot, force=force, test_only=test_only)

    if outfile:
        f.close()


def main():
    parser = argparse.ArgumentParser(prog='docs_gen')
    parser.add_argument('-t', '--test-only', action="store_true",
                        help="If given, don't generate images, but do try executing the scripts.")
    parser.add_argument('-k', '--keep-scripts', action="store_true",
                        help="If given, don't delete the temporary image OpenSCAD scripts.")
    parser.add_argument('-c', '--comments-only', action="store_true",
                        help='If given, only process lines that start with // comments.')
    parser.add_argument('-f', '--force', action="store_true",
                        help='If given, force generation of images when the code is unchanged.')
    parser.add_argument('-i', '--images', action="store_true",
                        help='If given, generate images for examples with OpenSCAD.')
    parser.add_argument('-I', '--imgroot', default="",
                        help='The directory to put generated images in.')
    parser.add_argument('-o', '--outfile',
                        help='Output file, if different from infile.')
    parser.add_argument('infile', help='Input filename.')
    args = parser.parse_args()

    imgprc.set_keep_scripts(args.keep_scripts)
    processFile(
        args.infile,
        outfile=args.outfile,
        gen_imgs=args.images,
        test_only=args.test_only,
        imgroot=args.imgroot,
        prefix="// " if args.comments_only else "",
        force=args.force
    )

    sys.exit(0)


if __name__ == "__main__":
    main()


# vim: expandtab tabstop=4 shiftwidth=4 softtabstop=4 nowrap
