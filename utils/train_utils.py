import tensorflow as tf

from tensorflow.image import random_crop, resize_with_crop_or_pad
from tensorflow.keras.losses import SparseCategoricalCrossentropy
from tensorflow.keras.metrics import Mean, SparseCategoricalAccuracy

import time
import numpy as np
import pickle as pkl

from models.conv_nets import make_convNet
from models.resnet import make_resnet18_UniformHe


def train_conv_nets(
    data_set,
    convnet_depth,
    convnet_widths,
    label_noise_as_int=10,
    n_batch_steps=500_000,
    batch_size=None,
    sample_size=None,
    optimizer=None,
    save=True,
    data_save_path_prefix="",
    data_save_path_suffix="",
    load_saved_metrics=False,
    data_augmentation=False
):
    """
    Train and save the results of Conv nets of a given range of model widths.

    Note: 500_000 is approximately 1250 epochs. 1_600_000 batchs is approximately 4K epochs.

    Parameters
    ----------

    data_set: str
        Which data set to train on. See the load data funciton.
    convnet_depth: int
    convnet_widths: list[int]
        List of model widths to train.
    label_noise_as_int: int
        Percentage of label noise to add to the training data.
    n_batch_steps: int
        number of gradient descent steps to take.
    batch_size: int
        Size of batchs to use during model training. Default to 128.
    sample_size: int
        Sample size to train the networks on. Used to replicate the sample-wise double descent results.
        Default is to use the entire data set (specified in data_set arg.)
    save: bool
        whether to save the data and trained model weights.
    data_save_path_prefix: str
        prefix to add to the save pkl file path.
    data_save_path_suffix: str
        suffix to add to the save pkl file name.
    load_saved_metrics: bool
        if True, will attempt to load the metrics from a previous training session in the save_path,
        to continue training from there. If True, will load the saved .pkl file instead of starting
        over and overwriting it. 
    """

    label_noise = label_noise_as_int / 100

    # load the relevent dataset. Note that the training data is cast to tf.float32 and normalized by 255.
    (x_train, y_train), (x_test, y_test), image_shape = load_data(
        data_set, label_noise, augment_data=data_augmentation, sample_size=sample_size
    )

    batch_size = 128 if batch_size is None else batch_size
    
    # total number desirec SGD steps / number batches per epoch = n_epochs
    n_epochs = n_batch_steps // (x_train.shape[0] // batch_size)
    n_classes = tf.math.reduce_max(y_train).numpy() + 1

    # store results for later graphing and analysis.
    model_histories = {}
    metrics = {}

    # Paths to save model weights and
    model_weights_paths = f"trained_model_weights_{data_set}/conv_nets_depth_{convnet_depth}_{label_noise_as_int}pct_noise/"
    data_save_path = (
        "experimental_results_{}/conv_nets_depth_{}_{}pct_noise".format(
            data_set, convnet_depth, label_noise_as_int
        ) + ".pkl"
    )

    # add possilbe data save path identifiers.
    if data_save_path_prefix:
        data_save_path = data_save_path_prefix + "/" + data_save_path

    if data_save_path_suffix:
        assert data_save_path[-4:] == ".pkl"
        data_save_path = data_save_path[:-4] + data_save_path_suffix + ".pkl"

    for width in convnet_widths:
        if load_saved_metrics and width in loaded_widths:
            print('width %d results already loaded from .pkl file, training skipped' %width)
            continue

        # Depth 5 Conv Net using default Kaiming Uniform Initialization.
        conv_net, model_id = make_convNet(
            image_shape, depth=convnet_depth, init_channels=width, n_classes=n_classes
        )

        conv_net.compile(
            optimizer=tf.keras.optimizers.SGD(learning_rate=inverse_squareroot_lr())
            if optimizer is None
            else optimizer,
            loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
            metrics=["accuracy"],
        )

        model_timer = timer()

        print(f"STARTING TRAINING: {model_id}")
        history = conv_net.fit(
            x=x_train,
            y=y_train,
            validation_data=(x_test, y_test),
            epochs=n_epochs,
            batch_size=batch_size,
            verbose=0,
            callbacks=[model_timer],
        )
        print(f"FINISHED TRAINING: {model_id}")

        # add results to dictionary and store the resulting model weights.
        metrics[model_id] = history.history

        # clear GPU of prior model to decrease training times.
        tf.keras.backend.clear_session()

        # Save results to the data file.
        if save:
            pkl.dump(metrics, open(data_save_path, "wb"))
            history.model.save_weights(model_weights_paths + model_id)

    return metrics


def train_resnet18(
    data_set,
    resnet_widths,
    label_noise_as_int=10,
    n_epochs=None,
    n_batch_steps=500_000,
    batch_size=None,
    sample_size=None,
    optimizer=None,
    save=True,
    data_save_path_prefix="",
    data_save_path_suffix="",
    load_saved_metrics=False
):
    """
    Train and save the results of ResNets nets of a given range of model widths.

    Parameters
    ----------
    data_set: str
        Which data set to train on. See the load data funciton.
    resnet_widths: list[int]
        List of model widths to train.
    label_noise_as_int: int
        Percentage of label noise to add to the training data.
    n_epochs: int
        number of epochs to train, if not specified, will calculate with n_batch_steps
    n_batch_steps: int
        number of gradient descent steps to take, over-ridden if n_epochs is specified
    batch_size: int
        Size of batchs to use during model training. Default to 128.
    sample_size: int
        Sample size to train the networks on. Used to replicate the sample-wise double descent results.
    optimizer: tf.keras.optimizer
        Optimizer to use while training resnets. Default is Adam with a learning rate of 1e-4.
    save: bool
        whether to save the data and trained model weights.
    data_save_path_prefix: str
        prefix to add to the save pkl file path.
    data_save_path_suffix: str
        suffix to add to the save pkl file name.
    load_saved_metrics: bool
        if True, will attempt to load the metrics from a previous training session in the save_path,
        to continue training from there. If True, will load the saved .pkl file instead of starting
        over and overwriting it. 
    """

    label_noise = label_noise_as_int / 100

    # load the relevent dataset
    (x_train, y_train), (x_test, y_test), image_shape = load_data(
        data_set, label_noise, augment_data=False, sample_size=sample_size
    )

    batch_size = 128 if batch_size is None else batch_size
    n_classes = tf.math.reduce_max(y_train).numpy() + 1

    # total number desirec SGD steps / number batches per epoch = n_epochs
    if not n_epochs:
        n_epochs = n_batch_steps // (x_train.shape[0] // batch_size)

    # store results for later graphing and analysis.
    model_histories = {}
    metrics = {}

    # Paths to save model weights and experimental results.
    model_weights_paths = f"trained_model_weights_{data_set}/resnet18_{label_noise_as_int}pct_noise/"
    data_save_path = (
        f"experimental_results_{data_set}/resnet18_{label_noise_as_int}pct_noise" + ".pkl"
    )

    # add possible path identifiers.
    if data_save_path_prefix:
        data_save_path = data_save_path_prefix + "/" + data_save_path
    if data_save_path_suffix:
        assert data_save_path[-4:] == ".pkl"
        data_save_path = data_save_path[:-4] + data_save_path_suffix + ".pkl"
    
    # load data from prior runs of related experiment.
    if load_saved_metrics:
        try:
            with open(data_save_path, 'rb') as f:
                metrics = pkl.load(f)
        except Exception as e:
            print('Could not find saved metrics.pkl file, exiting')
            raise e

        loaded_widths = [int(i.split('_')[-1]) for i in metrics.keys()]
        assert resnet_widths[:len(loaded_widths)] == loaded_widths
        print('loaded results for width %s from existing file at %s' %(', '.join([str(i) for i in loaded_widths]), data_save_path))

        assert data_save_path[-4:] == ".pkl"
        data_backup_path = data_save_path[:-4] + 'backup_w%d_' %loaded_widths[-1] + time.strftime("%D_%H%M%S").replace('/', '') + ".pkl"
        print('saving existing result.pkl to backup at %s' %data_backup_path)
        pkl.dump(metrics, open(data_backup_path, "wb"))


    for width in resnet_widths:
        if load_saved_metrics and width in loaded_widths:
            print('width %d results already loaded from .pkl file, training skipped' %width)
            continue

        # Resnet18 with Kaiming Uniform Initialization.
        resnet, model_id = make_resnet18_UniformHe(
            image_shape, k=width, num_classes=n_classes
        )

        # compile and pass input to initialize parameters.
        resnet.compile(
            optimizer=tf.keras.optimizers.Adam(1e-4)
            if optimizer is None
            else optimizer,
            loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
            metrics=["accuracy"],
        )
        
        # Custom Timer with cleaner output.
        model_timer = timer()

        print(f"STARTING TRAINING: {model_id}, Label Noise: {label_noise}")
        history = resnet.fit(
            x=x_train,
            y=y_train,
            validation_data=(x_test, y_test),
            epochs=n_epochs,
            batch_size=batch_size,
            verbose=0,
            callbacks=[model_timer],
        )
        print(f"FINISHED TRAINING: {model_id}")

        # add results to dictionary and store the resulting model weights.
        metrics[model_id] = history.history

        # clear GPU of prior model to decrease VRAM usage.
        tf.keras.backend.clear_session()

        # Save results to the data file
        if save:
            pkl.dump(metrics, open(data_save_path, "wb"))
            history.model.save_weights(model_weights_paths + model_id)

    return metrics


def load_data(data_set, label_noise, augment_data=False, sample_size=None):
    """
    Helper Function to Load data in the form of a tensorflow data set, apply label noise, and return the
    train data and test data.

    Parameters
    ----------
    data_set: str 
        name of data set to load from tf.keras.datasets
    label_noise: float
        percentage of training data to add noise to
    augment_data: boolean
        whether or not to use random cropping and horizontal flipping to augment training data
    sample_size: int
        The size of the data set to return.
    """

    datasets = ["cifar10", "cifar100", "mnist"]

    # load Cifar 10, Cifar 100, or mnis data set
    if data_set == "cifar10":
        get_data = tf.keras.datasets.cifar10
    elif data_set == "cifar100":
        get_data = tf.keras.datasets.cifar100
    elif data_set == "mnist":
        get_data = tf.keras.datasets.mnist
    else:
        raise Exception(
            f"Please enter a data set from the following options: {datasets}"
        )

    # load the data.
    (x_train, y_train), (x_test, y_test) = get_data.load_data()
    
    if sample_size is not None:
        idx = np.random.choice(y_train.shape[0], sample_size, replace=False)
        x_train, y_train = x_train[idx], y_train[idx]       

    # apply label noise to the data set
    if 0 < label_noise:
        random_idx = np.random.choice(
            y_train.shape[0], int(label_noise * y_train.shape[0]), replace=False
        )
        # To ensure that the random label is incorrct, we apply noise by first adding 
        # a random value between 1 (inclusive) and 10 (exclusive), and then taking modulo
        # 10. This guarantees the new value will be different from the original, while
        # also in the correct range.
        upper = y_train.max() + 1
        N = random_idx.shape[0]
        y_train[random_idx] = (y_train[random_idx] + np.random.randint(1, upper, (N, 1))) % upper
        
    if augment_data:
        (x_train,y_train) = augment_data_set(data_set, x_train, y_train )
    
    image_shape = x_train[0].shape
    # cast values to tf.float32 and normalize images to range [0-1]
    x_train, x_test = (
        tf.cast(x_train, tf.float32) / 255,
        tf.cast(x_test, tf.float32) / 255,
    )
    y_train, y_test = tf.cast(y_train, tf.int16), tf.cast(y_test, tf.int16)

    return (x_train, y_train), (x_test, y_test), list(image_shape)

class inverse_squareroot_lr:
    """
    This is the learning rate used with SGD in the paper (Inverse square root decay).
    Learning Rate starts at 0.1 and then drops every 512 batches.
    """

    def __init__(self, n_steps=512, init_lr=0.1):
        self.n = n_steps
        self.gradient_steps = 0
        self.init_lr = init_lr

    def __call__(self):
        lr = self.init_lr / tf.math.sqrt(
            1.0 + tf.math.floor(self.gradient_steps / self.n)
        )
        self.gradient_steps += 1
        return lr

def augment_data_set(data_set, x_train, y_train, crop_height=40, crop_width=40):
    """ 
        data_set: tf.data.Dataset (https://www.tensorflow.org/api_docs/python/tf/data/Dataset)
    Apply random cropping and random horizontal flip data augmentation as done in Deep Double Descent """
    
    # data augmentation is validated only for cifar10
    
    [height,width,channels] = x_train[0].shape
    
    if data_set == "cifar10":
        # duplicate the data so you will more data to train after random flip and crop
        data_x = np.concatenate((x_train, x_train), axis=0)
        y_train = np.concatenate((y_train, y_train), axis=0)

        #flip the images randomly
        data_x = tf.image.random_flip_left_right(data_x)

        #pad the data before croping
        npad = ((0, 0),(crop_height-height, crop_width-width), (crop_height-height, crop_width-width), (0, 0))
        data_x = np.pad(data_x, npad,'constant', constant_values = 125)

        x_train = tf.image.random_crop(data_x,[100000,32,32,3])

    return (x_train, y_train)


class timer(tf.keras.callbacks.Callback):
    """
    Simle call back class to track total training time.
    """

    def __init__(self, n_epochs=25):
        super().__init__()

        self.start_time = time.perf_counter()
        self.n_epochs = n_epochs

    def on_epoch_end(self, epoch, logs=None):
        """ Help keep track of total training time needed for various models. """
        if epoch % self.n_epochs == 0:
            end_time = time.perf_counter()
            run_time = end_time - self.start_time
            hrs, mnts, secs = (
                int(run_time // 60 // 60),
                int(run_time // 60 % 60),
                int(run_time % 60),
            )

            template = "Epoch: {:04}, Total Run Time: {:02}:{:02}:{:02}"
            template += " - Loss: {:.4e}, Accuracy: {:.3f}, Test Loss: {:.4e}, Test Accuracy: {:.3f}"

            train_loss, train_accuracy = logs["loss"], logs["accuracy"]
            test_loss, test_accuracy = logs["val_loss"], logs["val_accuracy"]
            print(
                template.format(
                    epoch,
                    hrs,
                    mnts,
                    secs,
                    train_loss,
                    train_accuracy,
                    test_loss,
                    test_accuracy,
                )
            )


class Model_Trainer:
    # Training Wrapper For Tensorflow Models. Allows a predifined model to be easily trained
    # while also tracking parameter and gradient information.

    # Please ensure that model_id is unique. It provides the path for all model statistics.

    """
    NO longer in use, model.fit provides significant training speed up. the features utilized below
    will be replaced with tensorflow callbacks.
    """

    def __init__(
        self, model, model_id, lr=1e-4, optimizer=None, data_augmentation=None
    ):
        """
        Parameters
        ----------

        model: tensorflow.keras.Model
        model_id : string
            An identifying string used in saving model metrics.
        lr : float, tensorflow.keras.optimizers.schedules
            If using the default optimizer, this is the lr used in the Adam optimizer.
            This value is ignored if an optimizer is passed to the trainer.
        optimizer : tensorflow.keras.optimizers
            A pre-defined optimizer used in training the neural network
        data_augmentation : tensorflow.keras.Sequential
            A tensorflow model used to perform data augmentation during training.
            See here: https://www.tensorflow.org/tutorials/images/data_augmentation#use_keras_preprocessing_layers
        """

        self.lr = lr

        self.model = model
        self.init_loss()

        # Can optionally pass a seperate optimizer.
        if optimizer is not None:
            self.optimizer = optimizer
        else:
            self.init_optimizer()

        if data_augmentation is not None:
            self.is_data_augmentation = True
            self.data_augmentation = data_augmentation
        else:
            self.is_data_augmentation = False
            self.data_augmentation = None

        # Used to save the parameters of the model at a given point of time.
        self.checkpoint = tf.train.Checkpoint(model=self.model)
        self.checkpoint_path = (
            self.model.__class__.__name__ + "/" + model_id + "/training_checkpoints"
        )

        self.summary_path = (
            self.model.__class__.__name__ + "/" + model_id + "/summaries/"
        )
        self.summary_writer = tf.summary.create_file_writer(self.summary_path)

        self.gradients = None

    # initialize loss function and metrics to track over training
    def init_loss(self):
        self.loss_function = SparseCategoricalCrossentropy()

        self.train_loss = Mean(name="train_loss")
        self.train_accuracy = SparseCategoricalAccuracy(name="train_accuracy")

        self.test_loss = Mean(name="test_loss")
        self.test_accuracy = SparseCategoricalAccuracy(name="test_accuracy")

    # Initialize Model optimizer
    def init_optimizer(self):
        self.optimizer = tf.keras.optimizers.Adam(learning_rate=self.lr, epsilon=1e-8)

    # Take a single Training step on the given batch of training data.
    def train_step(self, images, labels, track_gradient=False):

        with tf.GradientTape() as gtape:
            predictions = self.model(images, training=True)
            loss = self.loss_function(labels, predictions)

        gradients = gtape.gradient(loss, self.model.trainable_variables)
        self.optimizer.apply_gradients(zip(gradients, self.model.trainable_variables))

        # Track model Performance
        self.train_loss(loss)
        self.train_accuracy(labels, predictions)

        return self.train_loss.result(), self.train_accuracy.result() * 100

    # Evaluate Model on Test Data
    def test_step(self, data_set):
        predictions = self.model.predict(images)
        test_loss = self.loss_function(labels, predictions)

        self.test_loss(test_loss)
        self.test_accuracy(labels, predictions)

        return self.test_loss.result(), self.test_accuracy.result() * 100

    # Reset Metrics
    def reset(self):
        self.train_loss.reset_states()
        self.train_accuracy.reset_states()

        self.test_loss.reset_states()
        self.test_accuracy.reset_states()

    # Save a checkpoint instance of the model for later use
    def model_checkpoint(self):
        # Save a checkpoint to /tmp/training_checkpoints-{save_counter}
        save_path = self.checkpoint.save(self.checkpoint_path)
        return save_path

    def log_metrics(
        self,
    ):
        # Log metrics using tensorflow summary writer. Can Then visualize using TensorBoard
        step = self.checkpoint.save_counter

        with self.summary_writer.as_default():
            tf.summary.scalar("Train Loss", self.train_loss.result(), step=step)
            tf.summary.scalar("Train Accuracy", self.train_accuracy.result(), step=step)
            tf.summary.scalar("Test Loss", self.test_loss.result(), step=step)
            tf.summary.scalar("Test Accuracy", self.test_accuracy.result(), step=step)
