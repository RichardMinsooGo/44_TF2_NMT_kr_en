import os
import re
import time
import numpy as np
import matplotlib.pyplot as plt
import tensorflow as tf
import unicodedata

from tqdm import tqdm, tqdm_notebook, trange

from tensorflow.keras.layers import Dense, Input
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.models import Model

print("Tensorflow version {}".format(tf.__version__))
tf.random.set_seed(1234)
AUTO = tf.data.experimental.AUTOTUNE

ENCODER_LEN = 61
DECODER_LEN = ENCODER_LEN
BATCH_SIZE  = 128
BUFFER_SIZE = 20000

N_EPOCHS = 20

import urllib3
import zipfile
import shutil
import pandas as pd

pd.set_option('display.max_colwidth', None)

http = urllib3.PoolManager()
url = 'https://raw.githubusercontent.com/Huffon/pytorch-transformer-kor-eng/master/data/corpus.csv'
filename = 'corpus.csv'
path = os.getcwd()
zipfilename = os.path.join(path, filename)
with http.request('GET', url, preload_content=False) as r, open(zipfilename, 'wb') as out_file:       
    shutil.copyfileobj(r, out_file)

total_df = pd.read_csv('corpus.csv')

total_df.rename(columns={"english": "SRC"}, errors="raise", inplace=True)
total_df.rename(columns={"korean": "TRG"}, errors="raise", inplace=True)

total_df["src_len"] = ""
total_df["trg_len"] = ""
total_df.head()

for idx in range(len(total_df['SRC'])):
    # initialize string
    text_eng = str(total_df.iloc[idx]['SRC'])

    # default separator: space
    result_eng = len(text_eng.split())
    total_df.at[idx, 'src_len'] = int(result_eng)

    text_fra = str(total_df.iloc[idx]['TRG'])
    # default separator: space
    result_fra = len(text_fra.split())
    total_df.at[idx, 'trg_len'] = int(result_fra)

print('Translation Pair :',len(total_df)) # 리뷰 개수 출력

total_df = total_df.drop_duplicates(subset = ["SRC"])
print('Translation Pair :',len(total_df)) # 리뷰 개수 출력

total_df = total_df.drop_duplicates(subset = ["TRG"])
print('Translation Pair :',len(total_df)) # 리뷰 개수 출력

# 그 결과를 새로운 변수에 할당합니다.
is_within_len = (7 < total_df['src_len']) & (total_df['src_len'] <= 20) & (7 < total_df['trg_len']) & (total_df['trg_len'] <=20)
# 조건를 충족하는 데이터를 필터링하여 새로운 변수에 저장합니다.
total_df = total_df[is_within_len]
print('챗봇 샘플의 개수 :', len(total_df))

train_data = total_df.sample(n=1024*8, # number of items from axis to return.
          random_state=1234) # seed for random number generator for reproducibility
train_data.head()

print('챗봇 샘플의 개수 :', len(train_data))

print(train_data.isnull().sum())

raw_src = []
for sentence in train_data['SRC']:
    sentence = sentence.lower().strip()
    # creating a space between a word and the punctuation following it
    # eg: "he is a boy." => "he is a boy ."
    sentence = re.sub(r"([?.!,])", r" \1 ", sentence)
    sentence = re.sub(r'[" "]+', " ", sentence)
    # removing contractions
    sentence = re.sub(r"i'm", "i am", sentence)
    sentence = re.sub(r"he's", "he is", sentence)
    sentence = re.sub(r"she's", "she is", sentence)
    sentence = re.sub(r"it's", "it is", sentence)
    sentence = re.sub(r"that's", "that is", sentence)
    sentence = re.sub(r"what's", "that is", sentence)
    sentence = re.sub(r"where's", "where is", sentence)
    sentence = re.sub(r"how's", "how is", sentence)
    sentence = re.sub(r"\'ll", " will", sentence)
    sentence = re.sub(r"\'ve", " have", sentence)
    sentence = re.sub(r"\'re", " are", sentence)
    sentence = re.sub(r"\'d", " would", sentence)
    sentence = re.sub(r"\'re", " are", sentence)
    sentence = re.sub(r"won't", "will not", sentence)
    sentence = re.sub(r"can't", "cannot", sentence)
    sentence = re.sub(r"n't", " not", sentence)
    sentence = re.sub(r"n'", "ng", sentence)
    sentence = re.sub(r"'bout", "about", sentence)
    # replacing everything with space except (a-z, A-Z, ".", "?", "!", ",")
    sentence = re.sub(r"[^a-zA-Z?.!,]+", " ", sentence)
    sentence = sentence.strip()
    raw_src.append(sentence)

raw_trg = []
for sentence in train_data['TRG']:
    # 구두점에 대해서 띄어쓰기
    # ex) 12시 땡! -> 12시 땡 !
    sentence = re.sub(r"([?.!,])", r" \1 ", sentence)
    sentence = sentence.strip()
    raw_trg.append(sentence)

len(raw_src)

print(raw_src[:5])
print(raw_trg[:5])

df1 = pd.DataFrame(raw_src)
df2 = pd.DataFrame(raw_trg)

df1.rename(columns={0: "SRC"}, errors="raise", inplace=True)
df2.rename(columns={0: "TRG"}, errors="raise", inplace=True)
train_df = pd.concat([df1, df2], axis=1)

print('Translation Pair :',len(train_df)) # 리뷰 개수 출력

raw_src  = train_df['SRC']
raw_trg  = train_df['TRG']

special_tkns = "<PAD> <SOS> <EOS> <CLS> <SEP> <MASK> "
src_sentence  = raw_src.apply(lambda x: "<CLS> " + str(x) + " <SEP>")
trg_sentence  = raw_trg.apply(lambda x: str(x) + " <SEP>")

filters = '!"#$%&()*+,-./:;=?@[\\]^_`{|}~\t\n'
oov_token = '<unk>'

# Define tokenizer
SRC_tokenizer = tf.keras.preprocessing.text.Tokenizer(filters = filters, oov_token=oov_token)
TRG_tokenizer = tf.keras.preprocessing.text.Tokenizer(filters = filters, oov_token=oov_token)

SRC_tokenizer.fit_on_texts(special_tkns + src_sentence)
TRG_tokenizer.fit_on_texts(special_tkns + trg_sentence)

n_enc_vocab = len(SRC_tokenizer.word_index) + 7
n_dec_vocab = len(TRG_tokenizer.word_index) + 6

print('Encoder 단어 집합의 크기 :',n_enc_vocab)
print('Decoder 단어 집합의 크기 :',n_dec_vocab)

lines = [
  "It is winter and the weather is very cold.",
  "Will this Christmas be a white Christmas?",
  "Be careful not to catch a cold in winter and have a happy new year."
]
for line in lines:
    txt_2_ids = SRC_tokenizer.texts_to_sequences([line])
    ids_2_txt = SRC_tokenizer.sequences_to_texts(txt_2_ids)
    print("Input     :", line)
    print("txt_2_ids :", txt_2_ids)
    print("ids_2_txt :", ids_2_txt[0],"\n")

lines = [
  "게임하고싶은데 할래?",
  "나 너 좋아하는 것 같아",
  "딥 러닝 자연어 처리를 잘 하고 싶어"
]

for line in lines:
    txt_2_ids = TRG_tokenizer.texts_to_sequences([line])
    ids_2_txt = TRG_tokenizer.sequences_to_texts(txt_2_ids)
    print("Input     :", line)
    print("txt_2_ids :", txt_2_ids)
    print("ids_2_txt :", ids_2_txt[0],"\n")
    
# 토큰화 / 정수 인코딩 / 시작 토큰과 종료 토큰 추가 / 패딩
tokenized_inputs  = SRC_tokenizer.texts_to_sequences(src_sentence)
tokenized_outputs = TRG_tokenizer.texts_to_sequences(trg_sentence)

pad_idx = SRC_tokenizer.texts_to_sequences(['<PAD>'])

tkn_sources = []
tkn_targets = []

for idx in range(len(tokenized_inputs)):
    indexed_src_tkns = tokenized_inputs[idx] + [0] * (ENCODER_LEN - len(tokenized_inputs[idx]))
    indexed_trg_tkns = [0]*len(tokenized_inputs[idx]) + tokenized_outputs[idx] + [0]*(ENCODER_LEN - len(tokenized_inputs[idx])-len(tokenized_outputs[idx]))

    tkn_sources.append(indexed_src_tkns)
    tkn_targets.append(indexed_trg_tkns)

    
tensors_src = tf.cast(tkn_sources, dtype=tf.int64)
tensors_trg = tf.cast(tkn_targets, dtype=tf.int64)

print('질문 데이터의 크기(shape) :', tensors_src.shape)
print('답변 데이터의 크기(shape) :', tensors_trg.shape)

# 0번째 샘플을 임의로 출력
print(tensors_src[0])
print(tensors_trg[0])

n_layers  = 6     # 12
hid_dim   = 256
pf_dim    = 1024
n_heads   = 8
dropout   = 0.3

dataset = tf.data.Dataset.from_tensor_slices((tensors_src, tensors_trg))

dataset = dataset.cache()
dataset = dataset.shuffle(BUFFER_SIZE)
dataset = dataset.batch(BATCH_SIZE)
dataset = dataset.prefetch(tf.data.experimental.AUTOTUNE)

""" sinusoid position encoding """
def get_sinusoid_encoding_table(position, hid_dim):
    # angle_rads = get_angles(np.arange(position)[:, np.newaxis],
    #                         np.arange(hid_dim)[np.newaxis, :],
    #                         hid_dim)
    position = np.arange(position)[:, np.newaxis]
    angle_rates = 1 / np.power(10000, (2 * (np.arange(hid_dim)[np.newaxis, :]//2)) / np.float32(hid_dim))
    angle_rads =  position * angle_rates

    angle_rads[:, 0::2] = np.sin(angle_rads[:, 0::2])
    angle_rads[:, 1::2] = np.cos(angle_rads[:, 1::2])

    pos_encoding = angle_rads[np.newaxis, ...]

    return tf.cast(pos_encoding, dtype=tf.float32)

sample_pos_encoding = get_sinusoid_encoding_table(50, 128)

plt.pcolormesh(sample_pos_encoding.numpy()[0], cmap='RdBu')
plt.xlabel('Depth')
plt.xlim((0, 128))
plt.ylabel('Position')
plt.colorbar()
plt.show()

""" attention pad mask """
def create_padding_mask(seq):
    seq = tf.cast(tf.math.equal(seq, 0), tf.float32)
    # (batch_size, 1, 1, key의 문장 길이)
    return seq[:, tf.newaxis, tf.newaxis, :]

""" attention decoder mask """
def create_look_ahead_mask(size):
    mask = 1 - tf.linalg.band_part(tf.ones((size, size)), -1, 0)
    return mask

""" scale dot product attention """
def ScaledDotProductAttention(query, key, value, mask):
    """Calculate the attention weights.
    query, key, value must have matching leading dimensions.
    key, value must have matching penultimate dimension, i.e.: seq_len_k = seq_len_v.
    The mask has different shapes depending on its type(padding or look ahead)
    but it must be broadcastable for addition.
    
    query, key, value의 leading dimensions은 동일해야 합니다.
    key, value 에는 일치하는 끝에서 두 번째 차원이 있어야 합니다(예: seq_len_k = seq_len_v).
    MASK는 유형에 따라 모양이 다릅니다(패딩 혹은 미리보기(=look ahead)).
    그러나 추가하려면 브로드캐스트할 수 있어야 합니다.

    Args:
        query: query shape == (batch_size, n_heads, seq_len_q, depth)
        key: key shape     == (batch_size, n_heads, seq_len_k, depth)
        value: value shape == (batch_size, n_heads, seq_len_v, depth_v)
        mask: Float tensor with shape broadcastable
              to (batch_size, n_heads, seq_len_q, seq_len_k). Defaults to None.

    Returns:
        output, attention_weights
    """
    
    matmul_qk = tf.matmul(query, key, transpose_b=True)  # (..., seq_len_q, seq_len_k)

    # scale matmul_qk
    dk = tf.cast(tf.shape(key)[-1], tf.float32)
    scaled_attention_logits = matmul_qk / tf.math.sqrt(dk)

    # add the mask to the scaled tensor.
    if mask is not None:
        scaled_attention_logits += (mask * -1e9)

    # softmax is normalized on the last axis (seq_len_k) so that the scores
    # add up to 1.
    attention_weights = tf.nn.softmax(scaled_attention_logits, axis=-1)  # (..., seq_len_q, seq_len_k)

    output = tf.matmul(attention_weights, value)  # (..., seq_len_q, depth_v)

    return output, attention_weights

""" multi head attention """
class MultiHeadAttentionLayer(tf.keras.layers.Layer):
    
    def __init__(self, hid_dim, n_heads):
        super(MultiHeadAttentionLayer, self).__init__()
        self.n_heads = n_heads
        assert hid_dim % self.n_heads == 0
        self.hid_dim = hid_dim
        
        # hid_dim을 n_heads로 나눈 값.
        self.depth = int(hid_dim/self.n_heads)
        
        # WQ, WK, WV에 해당하는 밀집층 정의
        self.q_linear = tf.keras.layers.Dense(hid_dim)
        self.k_linear = tf.keras.layers.Dense(hid_dim)
        self.v_linear = tf.keras.layers.Dense(hid_dim)
        # WO에 해당하는 밀집층 정의
        self.out = tf.keras.layers.Dense(hid_dim)

    def split_heads(self, inputs, batch_size):
        """Split the last dimension into (n_heads, depth).
        Transpose the result such that the shape is (batch_size, n_heads, seq_len, depth)
        """
        inputs = tf.reshape(
            inputs, (batch_size, -1, self.n_heads, self.depth))
        return tf.transpose(inputs, perm=[0, 2, 1, 3])

    def call(self, value, key, query, mask):
        batch_size = tf.shape(query)[0]
        # 1. WQ, WK, WV에 해당하는 밀집층 지나기
        # q : (batch_size, query의 문장 길이, hid_dim)
        # k : (batch_size, key의 문장 길이, hid_dim)
        # v : (batch_size, value의 문장 길이, hid_dim)
        query = self.q_linear(query)
        key   = self.k_linear(key)
        value = self.v_linear(value)
        
        # 2. 헤드 나누기
        # q : (batch_size, n_heads, query의 문장 길이, hid_dim/n_heads)
        # k : (batch_size, n_heads, key의 문장 길이,   hid_dim/n_heads)
        # v : (batch_size, n_heads, value의 문장 길이, hid_dim/n_heads)
        query = self.split_heads(query, batch_size)
        key   = self.split_heads(key, batch_size)
        value = self.split_heads(value, batch_size)
        
        # 3. 스케일드 닷 프로덕트 어텐션. 앞서 구현한 함수 사용.
        # (batch_size, n_heads, query의 문장 길이, hid_dim/n_heads)
        # attention_weights.shape == (batch_size, n_heads, seq_len_q, seq_len_k)
        scaled_attention, attention_weights = ScaledDotProductAttention(
            query, key, value, mask)
        
        # (batch_size, query의 문장 길이, n_heads, hid_dim/n_heads)
        scaled_attention = tf.transpose(scaled_attention, perm=[0, 2, 1, 3])
        
        # 4. 헤드 연결(concatenate)하기
        # (batch_size, query의 문장 길이, hid_dim)
        concat_attention = tf.reshape(scaled_attention,
                                      (batch_size, -1, self.hid_dim))
        
        # 5. WO에 해당하는 밀집층 지나기
        # (batch_size, query의 문장 길이, hid_dim)
        outputs = self.out(concat_attention)

        return outputs, attention_weights

""" feed forward """
class PositionwiseFeedforwardLayer(tf.keras.layers.Layer):
    def __init__(self, hid_dim, pf_dim):
        super(PositionwiseFeedforwardLayer, self).__init__()
        self.linear_1 = tf.keras.layers.Dense(pf_dim, activation='relu')
        self.linear_2 = tf.keras.layers.Dense(hid_dim)

    def forward(self, attention):
        output = self.linear_1(attention)
        output = self.linear_2(output)
        return output

    
""" decoder layer """
class DecoderLayer(tf.keras.layers.Layer):
    def __init__(self, pf_dim, hid_dim, n_heads, dropout):
        super(DecoderLayer, self).__init__()

        self.attn   = MultiHeadAttentionLayer(hid_dim, n_heads)
        # self.attn_2 = MultiHeadAttentionLayer(hid_dim, n_heads)

        self.ffn = PositionwiseFeedforwardLayer(hid_dim, pf_dim)

        self.layernorm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        # self.layernorm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm3 = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        self.dropout1 = tf.keras.layers.Dropout(dropout)
        # self.dropout2 = tf.keras.layers.Dropout(dropout)
        self.dropout3 = tf.keras.layers.Dropout(dropout)

    def call(self, inputs, training, look_ahead_mask):
        # enc_output.shape == (batch_size, input_seq_len, hid_dim)

        attention1, attn_weights_block1 = self.attn(
            inputs, inputs, inputs, look_ahead_mask)  # (batch_size, target_seq_len, hid_dim)
        attention1 = self.dropout1(attention1, training=training)
        attention1 = self.layernorm1(inputs + attention1)

        # attention2, attn_weights_block2 = self.attn_2(
        #     enc_output, enc_output, attention1, padding_mask)  # (batch_size, target_seq_len, hid_dim)
        # attention2 = self.dropout2(attention2, training=training)
        # attention2 = self.layernorm2(attention1 + attention2)  # (batch_size, target_seq_len, hid_dim)

        ffn_outputs = self.ffn(attention1)  # (batch_size, target_seq_len, hid_dim)
        ffn_outputs = self.dropout3(ffn_outputs, training=training)
        ffn_outputs = self.layernorm3(attention1 + ffn_outputs)  # (batch_size, target_seq_len, hid_dim)

        return ffn_outputs, attn_weights_block1

""" decoder """
class Decoder(tf.keras.layers.Layer):
    def __init__(self, n_dec_vocab, n_layers, pf_dim, hid_dim, n_heads, 
                 maximum_position_encoding, dropout):
        super(Decoder, self).__init__()

        self.hid_dim = hid_dim
        self.n_layers = n_layers

        self.embedding = tf.keras.layers.Embedding(n_dec_vocab, hid_dim)
        self.pos_encoding = get_sinusoid_encoding_table(maximum_position_encoding, hid_dim)

        self.dec_layers = [DecoderLayer(pf_dim, hid_dim, n_heads, dropout)
                           for _ in range(n_layers)]
        self.dropout = tf.keras.layers.Dropout(dropout)

    def call(self, dec_input, training, look_ahead_mask):

        seq_len = tf.shape(dec_input)[1]
        attention_weights = {}

        emb = self.embedding(dec_input)
        emb *= tf.math.sqrt(tf.cast(self.hid_dim, tf.float32))
        emb += self.pos_encoding[:, :seq_len, :]

        output = self.dropout(emb, training=training)

        for i in range(self.n_layers):
            output, block1 = self.dec_layers[i](output, training, look_ahead_mask)

            attention_weights['decoder_layer{}_block1'.format(i+1)] = block1
    
        return output, attention_weights
    
def create_masks(tar):

    look_ahead_mask = create_look_ahead_mask(tf.shape(tar)[1])
    dec_target_padding_mask = create_padding_mask(tar)
    look_ahead_mask = tf.maximum(dec_target_padding_mask, look_ahead_mask)
  
    return look_ahead_mask

# Model Define for Training
""" transformer """
class GPT2(tf.keras.Model):

    def __init__(self, n_enc_vocab, n_dec_vocab,
                 n_layers, pf_dim, hid_dim, n_heads,
                 pe_input, pe_target, dropout):
        super(GPT2, self).__init__()

        self.decoder = Decoder(n_dec_vocab,
                               n_layers, pf_dim, hid_dim, n_heads,
                               pe_target, dropout)

        self.fin_output = tf.keras.layers.Dense(n_dec_vocab)
    
    def call(self, inp, training, look_ahead_mask):

        dec_output, attention_weights = self.decoder(inp, training, look_ahead_mask)

        final_output = self.fin_output(dec_output)

        return final_output, attention_weights

loss_object = tf.keras.losses.SparseCategoricalCrossentropy(
    from_logits=True, reduction='none')

def loss_function(real, pred):
    mask = tf.math.logical_not(tf.math.equal(real, 0))
    loss_ = loss_object(real, pred)

    mask = tf.cast(mask, dtype=loss_.dtype)
    loss_ *= mask

    return tf.reduce_sum(loss_)/tf.reduce_sum(mask)

class CustomSchedule(tf.keras.optimizers.schedules.LearningRateSchedule):
    def __init__(self, hid_dim, warmup_steps=4000):
        super(CustomSchedule, self).__init__()
        self.hid_dim = hid_dim
        self.hid_dim = tf.cast(self.hid_dim, tf.float32)
        self.warmup_steps = warmup_steps

    def __call__(self, step):
        arg1 = tf.math.rsqrt(step)
        arg2 = step * (self.warmup_steps ** -1.5)

        return tf.math.rsqrt(self.hid_dim) * tf.math.minimum(arg1, arg2)

learning_rate = CustomSchedule(hid_dim)

optimizer = tf.keras.optimizers.Adam(learning_rate, beta_1=0.9, beta_2=0.98,
                                     epsilon=1e-9)

temp_learning_rate_schedule = CustomSchedule(hid_dim)

plt.plot(temp_learning_rate_schedule(tf.range(40000, dtype=tf.float32)))
plt.ylabel("Learning Rate")
plt.xlabel("Train Step")

def accuracy_function(real, pred):
    accuracies = tf.equal(real, tf.argmax(pred, axis=2))
    mask = tf.math.logical_not(tf.math.equal(real, 0))
    accuracies = tf.math.logical_and(mask, accuracies)
    accuracies = tf.cast(accuracies, dtype=tf.float32)
    mask = tf.cast(mask, dtype=tf.float32)
    return tf.reduce_sum(accuracies)/tf.reduce_sum(mask)

train_loss = tf.keras.metrics.Mean(name='train_loss')
train_accuracy = tf.keras.metrics.Mean(name='train_accuracy')

"""## Training and checkpointing"""

model = GPT2(
    n_enc_vocab = n_enc_vocab,
    n_dec_vocab = n_dec_vocab,
    n_layers  = n_layers,
    pf_dim      = pf_dim,
    hid_dim     = hid_dim,
    n_heads     = n_heads,
    pe_input    = 512,
    pe_target   = 512,
    dropout     = dropout)

# tf.keras.utils.plot_model(
#     model, to_file='transformer.png', show_shapes=True)

checkpoint_path = "./checkpoints"

ckpt = tf.train.Checkpoint(model=model, optimizer=optimizer)

ckpt_manager = tf.train.CheckpointManager(ckpt, checkpoint_path, max_to_keep=5)

# if a checkpoint exists, restore the latest checkpoint.
if ckpt_manager.latest_checkpoint:
    ckpt.restore(ckpt_manager.latest_checkpoint)
    print('Latest checkpoint restored!!')

@tf.function
def train_step(inp, tar):

    combined_mask = create_masks(inp)

    with tf.GradientTape() as tape:
        predictions, _ = model(inp, True, combined_mask)
        loss = loss_function(tar, predictions)

    gradients = tape.gradient(loss, model.trainable_variables)
    optimizer.apply_gradients(zip(gradients, model.trainable_variables))

    train_loss(loss)
    train_accuracy(accuracy_function(tar, predictions))

for epoch in range(N_EPOCHS):
    train_loss.reset_states()
    
    with tqdm_notebook(total=len(dataset), desc=f"Train {epoch+1}") as pbar:
        for (batch, (inp, tar)) in enumerate(dataset):
            train_step(inp, tar)
    
            pbar.update(1)
            pbar.set_postfix_str(f"Loss {train_loss.result():.4f} Accuracy {train_accuracy.result():.4f}")
            
    # print(f'Epoch {epoch + 1} Loss {train_loss.result():.4f} Accuracy {train_accuracy.result():.4f}')
    
ckpt_save_path = ckpt_manager.save()
print ('Saving checkpoint for epoch {} at {}'.format(epoch+1, ckpt_save_path))

"""
def evaluate(text):
    text = SRC_tokenizer.texts_to_sequences([text])
    text = tf.keras.preprocessing.sequence.pad_sequences(text, maxlen=ENCODER_LEN,
                                                         padding='post', truncating='post')

    encoder_input = tf.expand_dims(text[0], 0)

    decoder_input = [TRG_tokenizer.word_index['<sos>']]
    output = tf.expand_dims(decoder_input, 0)
    
    for i in range(DECODER_LEN):
        enc_padding_mask, combined_mask, dec_padding_mask = create_masks(encoder_input, output)

        predictions, attention_weights = model(
            encoder_input, 
            output,
            False,
            enc_padding_mask,
            combined_mask,
            dec_padding_mask
        )

        predictions = predictions[:, -1:, :]
        predicted_id = tf.cast(tf.argmax(predictions, axis=-1), tf.int32)

        if predicted_id == TRG_tokenizer.word_index['<eos>']:
            return tf.squeeze(output, axis=0), attention_weights

        output = tf.concat([output, predicted_id], axis=-1)

    return tf.squeeze(output, axis=0), attention_weights

def predict(text):
    prediction = evaluate(text=text)[0].numpy()
    prediction = np.expand_dims(prediction[1:], 0)  
    predicted_sentence = TRG_tokenizer.sequences_to_texts(prediction)[0]
    
    return predicted_sentence

for idx in (11, 21, 31, 41, 51):
    print("Input        :", raw_src[idx])
    print("Prediction   :", predict(raw_src[idx]))
    print("Ground Truth :", raw_trg[idx],"\n")
"""    
