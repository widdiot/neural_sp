#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2018 Kyoto University (Hirofumi Inaguma)
#  Apache 2.0  (http://www.apache.org/licenses/LICENSE-2.0)

"""Base class for loading dataset for the CTC and attention-based model.
   In this class, all data will be loaded at each step.
   You can use the multi-GPU version.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import os
import pandas as pd

from neural_sp.datasets.base import Base
from neural_sp.datasets.token_converter.character import Char2idx
from neural_sp.datasets.token_converter.character import Idx2char
from neural_sp.datasets.token_converter.phone import Idx2phone
from neural_sp.datasets.token_converter.phone import Phone2idx
from neural_sp.datasets.token_converter.word import Idx2word
from neural_sp.datasets.token_converter.word import Word2idx
from neural_sp.datasets.token_converter.wordpiece import Idx2wp
from neural_sp.datasets.token_converter.wordpiece import Wp2idx
from utils import kaldi_io

np.random.seed(1)


class Dataset(Base):

    def __init__(self, tsv_path, dict_path,
                 unit, batch_size, n_epochs=None,
                 is_test=False, min_n_frames=40, max_n_frames=2000,
                 shuffle=False, sort_by_input_length=False,
                 short2long=False, sort_stop_epoch=None,
                 n_ques=None, dynamic_batching=False,
                 ctc=False, subsample_factor=1,
                 wp_model=False, corpus='',
                 concat_prev_n_utterances=0, cache_prev_n_tokens=0,
                 tsv_path_sub1=False, dict_path_sub1=False, unit_sub1=False,
                 wp_model_sub1=False,
                 ctc_sub1=False, subsample_factor_sub1=1,
                 wp_model_sub2=False,
                 tsv_path_sub2=False, dict_path_sub2=False, unit_sub2=False,
                 ctc_sub2=False, subsample_factor_sub2=1,
                 wp_model_sub3=False,
                 tsv_path_sub3=False, dict_path_sub3=False, unit_sub3=False,
                 ctc_sub3=False, subsample_factor_sub3=1):
        """A class for loading dataset.

        Args:
            tsv_path (str): path to the dataset tsv file
            dict_path (str): path to the dictionary
            unit (str): word or wp or char or phone or word_char
            batch_size (int): size of mini-batch
            n_epochs (int): max epoch. None means infinite loop.
            is_test (bool):
            min_n_frames (int): exclude utterances shorter than this value
            max_n_frames (int): exclude utterances longer than this value
            shuffle (bool): shuffle utterances.
                This is disabled when sort_by_input_length is True.
            sort_by_input_length (bool): sort all utterances in the ascending order
            short2long (bool): sort utterances in the descending order
            sort_stop_epoch (int): After sort_stop_epoch, training will revert
                back to a random order
            n_ques (int): number of elements to enqueue
            dynamic_batching (bool): change batch size dynamically in training
            ctc (bool):
            subsample_factor (int):
            wp_model (): path to the word-piece model for sentencepiece
            corpus (str): name of corpus
            concat_prev_n_utterances (int): number of utterances to concatenate
            cache_prev_n_tokens (int): number of previous tokens for cache (for training)

        """
        super(Dataset, self).__init__()

        self.set = os.path.basename(tsv_path).split('.')[0]
        self.is_test = is_test
        self.unit = unit
        self.unit_sub1 = unit_sub1
        self.batch_size = batch_size
        self.max_epoch = n_epochs
        self.shuffle = shuffle
        self.sort_stop_epoch = sort_stop_epoch
        self.sort_by_input_length = sort_by_input_length
        self.n_ques = n_ques
        self.dynamic_batching = dynamic_batching
        self.corpus = corpus
        self.concat_prev_n_utterances = concat_prev_n_utterances
        self.cache_prev_n_tokens = cache_prev_n_tokens
        self.vocab = self.count_vocab_size(dict_path)

        self.eos = 2
        self.pad = 3
        # NOTE: reserved in advance

        # Set index converter
        if unit in ['word', 'word_char']:
            self.idx2word = Idx2word(dict_path)
            self.word2idx = Word2idx(dict_path, word_char_mix=(unit == 'word_char'))
        elif unit == 'wp':
            self.idx2wp = Idx2wp(dict_path, wp_model)
            self.wp2idx = Wp2idx(dict_path, wp_model)
        elif unit == 'char':
            self.idx2char = Idx2char(dict_path)
            self.char2idx = Char2idx(dict_path)
        elif 'phone' in unit:
            self.idx2phone = Idx2phone(dict_path)
            self.phone2idx = Phone2idx(dict_path)
        else:
            raise ValueError(unit)

        for i in range(1, 4):
            dict_path_sub = locals()['dict_path_sub' + str(i)]
            wp_model_sub = locals()['wp_model_sub' + str(i)]
            unit_sub = locals()['unit_sub' + str(i)]
            if dict_path_sub:
                setattr(self, 'vocab_sub' + str(i), self.count_vocab_size(dict_path_sub))

                # Set index converter
                if unit_sub:
                    if unit_sub == 'wp':
                        setattr(self, 'idx2wp_sub' + str(i), Idx2wp(dict_path_sub, wp_model_sub))
                        setattr(self, 'wp2idx_sub' + str(i), Wp2idx(dict_path_sub, wp_model_sub))
                    elif unit_sub == 'char':
                        setattr(self, 'idx2char_sub' + str(i), Idx2char(dict_path_sub))
                        setattr(self, 'char2idx_sub' + str(i), Char2idx(dict_path_sub))
                    elif 'phone' in unit_sub:
                        setattr(self, 'idx2phone_sub' + str(i),  Idx2phone(dict_path_sub))
                        setattr(self, 'phone2idx_sub' + str(i),  Phone2idx(dict_path_sub))
                    else:
                        raise ValueError(unit_sub)

                assert concat_prev_n_utterances == 0
                assert cache_prev_n_tokens == 0
                # TODO(hirofumi): fix later
            else:
                setattr(self, 'vocab_sub' + str(i), -1)

        # Load dataset tsv file
        self.df = pd.read_csv(tsv_path, encoding='utf-8', delimiter='\t')
        self.df = self.df.loc[:, ['utt_id', 'speaker', 'feat_path',
                                  'xlen', 'xdim', 'text', 'token_id', 'ylen', 'ydim']]
        for i in range(1, 4):
            if locals()['tsv_path_sub' + str(i)]:
                df_sub = pd.read_csv(locals()['tsv_path_sub' + str(i)], encoding='utf-8', delimiter='\t')
                df_sub = df_sub.loc[:, ['utt_id', 'speaker', 'feat_path',
                                        'xlen', 'xdim', 'text', 'token_id', 'ylen', 'ydim']]
                setattr(self, 'df_sub' + str(i), df_sub)
            else:
                setattr(self, 'df_sub' + str(i), None)

        # For cache decoding
        if corpus == 'swbd':
            self.df['session'] = self.df['speaker'].apply(lambda x: str(x).split('-')[0])
        else:
            self.df['session'] = self.df['speaker'].apply(lambda x: str(x))

        if concat_prev_n_utterances > 0 or cache_prev_n_tokens > 0:
            assert corpus in ['swbd', 'csj', 'librispeech']
            max_n_frames = 10000
            min_n_frames = 1

            # Sort by onset
            self.df = self.df.assign(prev_utt='')
            if corpus == 'swbd':
                self.df['onset'] = self.df['utt_id'].apply(lambda x: int(x.split('_')[-1].split('-')[0]))
            elif corpus == 'csj':
                self.df['onset'] = self.df['utt_id'].apply(lambda x: int(x.split('_')[1]))
            else:
                raise NotImplementedError
            self.df = self.df.sort_values(by=['session', 'onset'], ascending=True)

            # Extract previous utterances
            if not (is_test and cache_prev_n_tokens > 0):
                self.df = self.df.assign(line_no=list(range(len(self.df))))
                groups = self.df.groupby('session').groups  # dict
                self.df['prev_utt'] = self.df.apply(
                    lambda x: [self.df.loc[i, 'line_no']
                               for i in groups[x['session']] if self.df.loc[i, 'onset'] < x['onset']], axis=1)
        elif is_test and corpus == 'swbd':
            # Sort by onset
            self.df['onset'] = self.df['utt_id'].apply(lambda x: int(x.split('_')[-1].split('-')[0]))
            self.df = self.df.sort_values(by=['session', 'onset'], ascending=True)

        if concat_prev_n_utterances > 0:
            assert cache_prev_n_tokens == 0
            # Truncate history
            self.df['prev_utt'] = self.df['prev_utt'].apply(lambda x: x[-concat_prev_n_utterances:])

            # Update xlen, ylen, text
            self.pad_xlen = 20
            self.df['xlen'] = self.df.apply(
                lambda x: sum([self.df.loc[i, 'xlen'] + self.pad_xlen
                               for i in x['prev_utt']] + [x['xlen']]) if len(x['prev_utt']) > 0 else x['xlen'], axis=1)
            self.df['ylen'] = self.df.apply(
                lambda x: sum([self.df.loc[i, 'ylen'] + 1
                               for i in x['prev_utt']] + [x['ylen']]) if len(x['prev_utt']) > 0 else x['ylen'], axis=1)
            self.df['text'] = self.df.apply(
                lambda x: ' '.join([self.df.loc[i, 'text']
                                    for i in x['prev_utt']] + [x['text']]) if len(x['prev_utt']) > 0 else x['text'], axis=1)

        if cache_prev_n_tokens > 0:
            assert concat_prev_n_utterances == 0

        # Remove inappropriate utterances
        if is_test:
            print('Original utterance num: %d' % len(self.df))
            n_utts = len(self.df)
            self.df = self.df[self.df.apply(lambda x: x['ylen'] > 0, axis=1)]
            print('Removed %d empty utterances' % (n_utts - len(self.df)))
        else:
            print('Original utterance num: %d' % len(self.df))
            n_utts = len(self.df)
            self.df = self.df[self.df.apply(lambda x: min_n_frames <= x[
                                            'xlen'] <= max_n_frames, axis=1)]
            self.df = self.df[self.df.apply(lambda x: x['ylen'] > 0, axis=1)]
            print('Removed %d utterances (threshold)' % (n_utts - len(self.df)))

            if ctc and subsample_factor > 1:
                n_utts = len(self.df)
                self.df = self.df[self.df.apply(lambda x: x['ylen'] <= x['xlen'] // subsample_factor, axis=1)]
                print('Removed %d utterances (for CTC)' % (n_utts - len(self.df)))

            for i in range(1, 4):
                df_sub = getattr(self, 'df_sub' + str(i))
                ctc_sub = locals()['ctc_sub' + str(i)]
                subsample_factor_sub = locals()['subsample_factor_sub' + str(i)]
                if df_sub is not None:
                    if ctc_sub and subsample_factor_sub > 1:
                        df_sub = df_sub[df_sub.apply(lambda x: x['ylen'] <= x['xlen'] // subsample_factor_sub, axis=1)]

                    if len(self.df) != len(df_sub):
                        n_utts = len(self.df)
                        self.df = self.df.drop(self.df.index.difference(df_sub.index))
                        print('Removed %d utterances (for CTC, sub%d)' % (n_utts - len(self.df), i))
                        for j in range(1, i + 1):
                            setattr(self, 'df_sub' + str(j),
                                    getattr(self, 'df_sub' + str(j)).drop(getattr(self, 'df_sub' + str(j)).index.difference(self.df.index)))

        # Sort tsv records
        if not is_test:
            if sort_by_input_length:
                self.df = self.df.sort_values(by='xlen', ascending=short2long)
            elif shuffle:
                self.df = self.df.reindex(np.random.permutation(self.df.index))
            elif not (concat_prev_n_utterances > 0 or cache_prev_n_tokens > 0):
                self.df = self.df.sort_values(by='utt_id', ascending=True)

        self.rest = set(list(self.df.index))
        self.input_dim = kaldi_io.read_mat(self.df['feat_path'][0]).shape[-1]

    def make_batch(self, df_indices):
        """Create mini-batch per step.

        Args:
            df_indices (np.ndarray):
        Returns:
            batch (dict):
                xs (list): input data of size `[T, input_dim]`
                xlens (list): lengths of each element in xs
                ys (list): reference labels in the main task of size `[L]`
                ys_sub1 (list): reference labels in the 1st auxiliary task of size `[L_sub1]`
                ys_sub2 (list): reference labels in the 2nd auxiliary task of size `[L_sub2]`
                ys_sub3 (list): reference labels in the 3rd auxiliary task of size `[L_sub3]`
                utt_ids (list): name of each utterance
                speakers (list): name of each speaker
                sessions (list): name of each session

        """
        # inputs
        xs = [kaldi_io.read_mat(self.df['feat_path'][i]) for i in df_indices]
        if self.concat_prev_n_utterances > 0:
            for j, i in enumerate(df_indices):
                for i_prev in self.df['prev_utt'][i][::-1]:
                    x_prev = kaldi_io.read_mat(self.df['feat_path'][i_prev])
                    xs[j] = np.concatenate(
                        [x_prev, np.zeros((self.pad_xlen, self.input_dim), dtype=np.float32), xs[j]], axis=0)

        # outputs
        ys = [list(map(int, str(self.df['token_id'][i]).split())) for i in df_indices]
        if self.concat_prev_n_utterances > 0:
            for j, i in enumerate(df_indices):
                for i_prev in self.df['prev_utt'][i][::-1]:
                    y_prev = list(map(int, str(self.df['token_id'][i_prev]).split()))
                    ys[j] = y_prev + [self.eos] + ys[j][:]

        ys_cache = []
        if self.cache_prev_n_tokens > 0:
            ys_cache = [[] for _ in range(len(df_indices))]
            for j, i in enumerate(df_indices):
                for i_prev in self.df['prev_utt'][i]:
                    y_prev = list(map(int, str(self.df['token_id'][i_prev]).split()))
                    ys_cache[j] += [self.eos] + y_prev

            # Truencate
            ys_cache = [y[-self.cache_prev_n_tokens:] for y in ys_cache]

        ys_sub1 = []
        if self.df_sub1 is not None:
            ys_sub1 = [list(map(int, self.df_sub1['token_id'][i].split())) for i in df_indices]

        ys_sub2 = []
        if self.df_sub2 is not None:
            ys_sub2 = [list(map(int, self.df_sub2['token_id'][i].split())) for i in df_indices]

        ys_sub3 = []
        if self.df_sub3 is not None:
            ys_sub3 = [list(map(int, self.df_sub3['token_id'][i].split())) for i in df_indices]

        batch_dict = {
            'xs': xs,
            'xlens': [self.df['xlen'][i] for i in df_indices],
            'ys': ys,
            'ys_cache': ys_cache,
            'ys_sub1': ys_sub1,
            'ys_sub2': ys_sub2,
            'ys_sub3': ys_sub3,
            'utt_ids':  [self.df['utt_id'][i] for i in df_indices],
            'speakers': [self.df['speaker'][i] for i in df_indices],
            'sessions': [self.df['session'][i] for i in df_indices],
            'text': [self.df['text'][i] for i in df_indices],
            'feat_path': [self.df['feat_path'][i] for i in df_indices]  # for plot
        }

        return batch_dict
